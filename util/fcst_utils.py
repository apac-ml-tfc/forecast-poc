# Python Built-Ins:
import gzip
import json
import time
from typing import Union

# External Dependencies:
import boto3
import botocore.exceptions
import matplotlib as mpl
import matplotlib.pyplot as plt
import pandas as pd

# Local Dependencies:
import util.notebook_utils


def wait_till_delete(callback, check_time = 5, timeout = None):

    elapsed_time = 0
    while timeout is None or elapsed_time < timeout:
        try:
            out = callback()
        except botocore.exceptions.ClientError as e:
            # When given the resource not found exception, deletion has occured
            if e.response['Error']['Code'] == 'ResourceNotFoundException':
                print('Successful delete')
                return
            else:
                raise
        time.sleep(check_time)  # units of seconds
        elapsed_time += check_time

    raise TimeoutError( "Forecast resource deletion timed-out." )


def wait(callback, time_interval = 10):

    status_indicator = util.notebook_utils.StatusIndicator()

    while True:
        status = callback()['Status']
        status_indicator.update(status)
        if status in ('ACTIVE', 'CREATE_FAILED'): break
        time.sleep(time_interval)

    status_indicator.end()
    
    return (status=="ACTIVE")


def load_exact_sol(fname, item_id, is_schema_perm=False):
    exact = pd.read_csv(fname, header = None)
    exact.columns = ['item_id', 'timestamp', 'target']
    if is_schema_perm:
        exact.columns = ['timestamp', 'target', 'item_id']
    return exact.loc[exact['item_id'] == item_id]


def get_or_create_role_arn(boto_session=None):
    iam = (boto_session if boto_session else boto3).resource("iam")
    role_name = "ForecastRoleDemo"
    assume_role_policy_document = {
        "Version": "2012-10-17",
        "Statement": [
            {
              "Effect": "Allow",
              "Principal": {
                "Service": "forecast.amazonaws.com"
              },
              "Action": "sts:AssumeRole"
            }
        ]
    }
    role_arn = None
    need_sleep = False
    try:
        create_role_response = iam.create_role(
            RoleName=role_name,
            AssumeRolePolicyDocument=json.dumps(assume_role_policy_document),
        )
        need_sleep = True
        role_arn = create_role_response["Role"]["Arn"]
    except iam.exceptions.EntityAlreadyExistsException:
        print("The role " + role_name + " exists, ignore to create it")
        role_arn = iam.Role(role_name).arn
    policy_arn = "arn:aws:iam::aws:policy/AmazonForecastFullAccess"
    iam.attach_role_policy(
        RoleName = role_name,
        PolicyArn = policy_arn
    )
    iam.attach_role_policy(
        PolicyArn='arn:aws:iam::aws:policy/AmazonS3FullAccess',
        RoleName=role_name
    )
    if need_sleep:
        time.sleep(60) # wait for a minute to allow IAM role policy attachment to propagate
    print(role_arn)
    return role_arn


# def plot_forecasts(fcsts, exact, freq = '1H', forecastHorizon=24, time_back = 80):
#     p10 = pd.DataFrame(fcsts['Forecast']['Predictions']['p10'])
#     p50 = pd.DataFrame(fcsts['Forecast']['Predictions']['p50'])
#     p90 = pd.DataFrame(fcsts['Forecast']['Predictions']['p90'])
#     pred_int = p50['Timestamp'].apply(lambda x: pd.Timestamp(x))
#     fcst_start_date = pred_int[0]
#     time_int = exact['timestamp'].apply(lambda x: pd.Timestamp(x))
#     plt.plot(time_int[-time_back:],exact['target'].values[-time_back:], color = 'r')
#     plt.plot(pred_int, p50['Value'].values, color = 'k');
#     plt.fill_between(p50['Timestamp'].values, 
#                      p10['Value'].values,
#                      p90['Value'].values,
#                      color='b', alpha=0.3);
#     plt.axvline(x=pd.Timestamp(fcst_start_date), linewidth=3, color='g', ls='dashed');
#     plt.axvline(x=pd.Timestamp(fcst_start_date, freq)+forecastHorizon-1, linewidth=3, color='g', ls='dashed');
#     plt.xticks(rotation=30);
#     plt.legend(['Target', 'Forecast'], loc = 'lower left')


def extract_gz( src, dst ):
    
    print( f"Extracting {src} to {dst}" )    

    with open(dst, 'wb') as fd_dst:
        with gzip.GzipFile( src, 'rb') as fd_src:
            data = fd_src.read()
            fd_dst.write(data)

    print("Done.")

def extract_json_values(obj, key):
    """Pull all values of specified key from nested JSON."""
    arr = []

    def extract(obj, arr, key):
        """Recursively search for values of key in JSON tree."""
        if isinstance(obj, dict):
            for k, v in obj.items():
                if isinstance(v, (dict, list)):
                    extract(v, arr, key)
                elif k == key:
                    arr.append(v)
        elif isinstance(obj, list):
            for item in obj:
                extract(item, arr, key)
        return arr

    results = extract(obj, arr, key)
    return results


def plot_forecasts(
    forecasts: pd.DataFrame,
    actuals: Union[pd.DataFrame, None]=None,
    xlabel: str="Date",
    ylabel: str="Value",
):
    """Plot 10/50/90 quantile forecast(s) with optional actual data overlay

    Arguments
    ---------
    forecasts : pandas.DataFrame
        Must be indexed by date/timestamp. May include `p10` and `p90` columns (plotted as a confidence
        band if both supplied). May include `p50` and `mean` columns (plotted as lines). May include multiple
        forecasts via optional `item_id` column (generates separate plots).
    actuals : pandas.DataFrame (Optional)
        Must be indexed by date/timestamp and include `actual` column. Presence or absence of `item_id`
        column match `forecast` argument.
    """

    item_ids = forecasts["item_id"].unique() if "item_id" in forecasts else [None]

    for item_id in item_ids:
        forecast = forecasts if item_id is None else forecasts[forecasts["item_id"] == item_id]
        forecast_tsnums = mpl.dates.date2num(forecast.index)

        # Create our figure:
        fig = plt.figure(figsize=(15, 6))
        ax = plt.gca()
        ax.set_title(f"Item {item_id}")

        if "p10" in forecast and "p90" in forecast:
            # Translucent color-1 fill covering the confidence interval:
            ax.fill_between(
                forecast_tsnums,
                forecast["p10"],
                forecast["p90"],
                alpha=0.3,
                label="80% Confidence Interval",
            )

        if actuals is not None:
            # A black line plot of the actuals (training + test):
            actual = actuals if item_id is None else actuals[actuals["item_id"] == item_id]
            ax.plot_date(
                mpl.dates.date2num(actual.index),
                actual["actual"],
                fmt="-",
                color="black",
                label="Actual",
            )

        if "p50" in forecast:
            # Color-1 line identifying the prediction median:
            ax.plot_date(
                forecast_tsnums,
                forecast["p50"],
                fmt="-",
                label="Prediction Median"
            )
        if "mean" in forecast:
            # Color-2 line identifying the prediction mean:
            ax.plot_date(
                forecast_tsnums,
                forecast["mean"],
                fmt="-",
                label="Prediction Mean"
            )

        ax.set_xlabel(xlabel)
        ax.set_ylabel(ylabel)
        ax.legend()
        plt.show()
