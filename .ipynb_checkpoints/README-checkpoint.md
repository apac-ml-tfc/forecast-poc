# Forecast POC Guide

Amazon Forecast is a machine learning service that allows you to build and scale time series models in a quick and effective process. The content below is designed to help you build out your first models for your given use case and makes assumptions that your data may not yet be in an ideal format for Amazon Forecast to use.

This repository assumes a base familiarity with the service and if you have not already done so it is recommended that you use the getting-started material below.

## Introduction to Amazon Forecast

If you are not familiar with Amazon Forecast you can learn more about this tool on these pages:

* [Product Page](https://aws.amazon.com/forecast/)
* [GitHub Sample Notebooks](https://github.com/aws-samples/amazon-forecast-samples)
* [Product Docs](https://docs.aws.amazon.com/forecast/latest/dg/what-is-forecast.html)


## Process:

1. Deploying Your Working Environment
1. Validating and Importing Target Time Series Data
1. Creating and Evaluating Your First Predictors
1. Validating and Importing Related Time Series Data
1. Creating and Evaluating Your Predictors With Related Time Series Data

That is a genereal order to this proccess, however if you are operating this as an assisted 2 day on-site POC. It is recommended that you operate steps 2 and 4 beforehand. Once the related data has been successfully imported you can delete it so that it does not muddy the results from your first Predictor.


## Deploying Your Working Environment

#TODO: Lift this from the existing samples repo

## Validating and Importing Target Time Series Data

Open `Validating_and_Importing_Target_Time_Series_Data.ipynb` and follow along there.