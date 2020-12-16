"""Custom CloudFormation Resource for a SageMaker Studio Domain (with additional outputs)

As well as creating a SMStudio domain, this implementation:
- Defaults to the default VPC, or to any VPC when exactly one is present, if not explicitly configured
- Defaults to all default subnets if any are present, or else all subnets in VPC, if not explicitly set
- Discovers and outputs a list of security group IDs (default+SM-generated) that downstream resources may use
  to perform user setup actions on the Elastic File System
"""

# Python Built-Ins:
import json
import logging
import time
import traceback

# External Dependencies:
import boto3
from botocore.exceptions import ClientError
import cfnresponse

ec2 = boto3.client("ec2")
smclient = boto3.client("sagemaker")

def lambda_handler(event, context):
    try:
        request_type = event["RequestType"]
        if request_type == "Create":
            handle_create(event, context)
        elif request_type == "Update":
            handle_update(event, context)
        elif request_type == "Delete":
            handle_delete(event, context)
        else:
            cfnresponse.send(
                event,
                context,
                cfnresponse.FAILED,
                {},
                error=f"Unsupported CFN RequestType '{request_type}'",
            )
    except Exception as e:
        logging.error("Uncaught exception in CFN custom resource handler - reporting failure")
        traceback.print_exc()
        cfnresponse.send(
            event,
            context,
            cfnresponse.FAILED,
            {},
            error=str(e),
        )
        raise e


def handle_create(event, context):
    logging.info("**Received create request")
    resource_config = event["ResourceProperties"]

    logging.info("**Creating studio domain")
    response_data = create_studio_domain(resource_config)
    cfnresponse.send(
        event,
        context,
        cfnresponse.SUCCESS,
        {
            "DomainId": response_data["DomainId"],
            "DomainName": response_data["DomainName"],
            "HomeEfsFileSystemId": response_data["HomeEfsFileSystemId"],
            "SubnetIds": ",".join(response_data["SubnetIds"]),
            "SecurityGroupIds": ",".join(response_data["SecurityGroupIds"]),
            "Url": response_data["Url"],
            "VpcId": response_data["VpcId"],
        },
        physicalResourceId=response_data["DomainId"],
    )


def handle_delete(event, context):
    logging.info("**Received delete event")
    domain_id = event["PhysicalResourceId"]
    try:
        smclient.describe_domain(DomainId=domain_id)
    except smclient.exceptions.ResourceNotFound as exception:
        # Already does not exist -> deletion success
        cfnresponse.send(
            event,
            context,
            cfnresponse.SUCCESS,
            {},
            physicalResourceId=event["PhysicalResourceId"],
        )
        return
    logging.info("**Deleting studio domain")
    delete_domain(domain_id)
    cfnresponse.send(
        event,
        context,
        cfnresponse.SUCCESS,
        {},
        physicalResourceId=event["PhysicalResourceId"],
    )


def handle_update(event, context):
    logging.info("**Received update event")
    domain_id = event["PhysicalResourceId"]
    default_user_settings = event["ResourceProperties"]["DefaultUserSettings"]
    logging.info("**Updating studio domain")
    update_domain(domain_id, default_user_settings)
    # TODO: Should we wait here for the domain to enter active state again?
    cfnresponse.send(
        event,
        context,
        cfnresponse.SUCCESS,
        { "DomainId" : domain_id },
        physicalResourceId=event["PhysicalResourceId"],
    )


def create_studio_domain(config):
    default_user_settings = config["DefaultUserSettings"]
    domain_name = config["DomainName"]
    vpc_id = config.get("VPC")
    subnet_ids = config.get("SubnetIds")
    security_group_ids = config.get("SecurityGroupIds")

    if not vpc_id:
        # Try to look up the default VPC ID:
        # TODO: NextToken handling on this list API?
        available_vpcs = ec2.describe_vpcs()["Vpcs"]
        if len(available_vpcs) <= 0:
            raise ValueError("No default VPC exists - cannot create SageMaker Studio Domain")

        default_vpcs = list(filter(lambda v: v["IsDefault"], available_vpcs))
        if len(default_vpcs) == 1:
            vpc = default_vpcs[0]
        elif len(default_vpcs) > 1:
            raise ValueError("'VPC' not specified in config, and multiple default VPCs found")
        else:
            if len(available_vpcs) == 1:
                vpc = available_vpcs[0]
                logging.warning(f"Found exactly one (non-default) VPC: Using {vpc['VpcId']}")
            else:
                raise ValueError(
                    "'VPC' not specified in config, and multiple VPCs found with no 'default' VPC"
                )
        vpc_id = vpc["VpcId"]

    if not subnet_ids:
        # Use all the subnets
        # TODO: NextToken handling on this list API?
        available_subnets = ec2.describe_subnets(
            Filters=[{
                "Name": "vpc-id",
                "Values": [vpc_id],
            }],
        )["Subnets"]
        default_subnets = list(filter(lambda n: n["DefaultForAz"], available_subnets))
        subnet_ids = [
            n["SubnetId"] for n in
            (default_subnets if len(default_subnets) > 0 else available_subnets)
        ]
    elif isinstance(subnet_ids, str):
        subnet_ids = subnet_ids.split(",")

    response = smclient.create_domain(
        DomainName=domain_name,
        AuthMode="IAM",
        DefaultUserSettings=default_user_settings,
        SubnetIds=subnet_ids,
        VpcId=vpc_id,
    )

    domain_id = response["DomainArn"].split("/")[-1]
    created = False
    time.sleep(0.2)
    while not created:
        response = smclient.describe_domain(DomainId=domain_id)
        if response["Status"] == "InService":
            created = True
            break
        time.sleep(5)
    logging.info("**SageMaker domain created successfully: %s", domain_id)

    if not security_group_ids:
        available_security_groups = ec2.describe_security_groups(
            Filters=[
                { "Name": "vpc-id", "Values": [vpc_id] },
            ],
        )["SecurityGroups"]
        print(f"Found {len(available_security_groups)} security groups in VPC")
        nfs_security_groups = ec2.describe_security_groups(
            Filters=[
                { "Name": "vpc-id", "Values": [vpc_id] },
                {
                    "Name": "group-name",
                    "Values": [
                        f"security-group-for-outbound-nfs-{domain_id}",
                        f"security-group-for-inbound-nfs-{domain_id}",
                    ],
                },
            ],
        )["SecurityGroups"]
        print(f"Found {len(nfs_security_groups)} security groups associated with SMStudio")
        public_security_groups = list(filter(
            lambda sg: len(list(filter(
                lambda perm: len(list(filter(
                    lambda ip_range: ip_range.get("CidrIp") == "0.0.0.0/0",
                    perm.get("IpRanges", []),
                ))),
                sg.get("IpPermissionsEgress", []),
            ))),
            available_security_groups,
        ))
        print(f"Found {len(public_security_groups)} security groups with public access")
        if len(nfs_security_groups) > 1 and len(nfs_security_groups) < 5:
            print("Setting preferred config")
            security_group_ids = list(
                map(lambda sg: sg["GroupId"], nfs_security_groups)
            )
            if len(public_security_groups) > 0:
                security_group_ids.append(public_security_groups[0]["GroupId"])
                print(f"Using preferred SG config {security_group_ids}")
            else:
                print(f"Using NFS SG config with NO PUBLIC SGs {security_group_ids}")
        elif len(public_security_groups) == 1:
            print(f"Found exactly one public security group:\n{public_security_groups[0]}")
            security_group_ids = [public_security_groups[0]["GroupId"]]
        elif len(public_security_groups) > 1:
            print(f"Found {len(public_security_groups)} public security groups:\n{public_security_groups}")
            security_group_ids = [public_security_groups[0]["GroupId"]]
        elif len(available_security_groups) == 1:
            print(f"Found exactly one (non-public) security group:\n{available_security_groups[0]}")
            security_group_ids = [available_security_groups[0]["GroupId"]]
        elif len(available_security_groups) > 1:
            print(f"Found {len(available_security_groups)} (non-public) security groups:\n{available_security_groups}")
            security_group_ids = [available_security_groups[0]["GroupId"]]
        else:
            raise ValueError(f"Couldn't find any security groups in VPC {vpc_id}!")

    response["SecurityGroupIds"] = security_group_ids
    return response


def delete_domain(domain_id):
    response = smclient.delete_domain(
        DomainId=domain_id,
        RetentionPolicy={
            "HomeEfsFileSystem": "Delete"
        },
    )
    deleted = False
    time.sleep(0.2)
    while not deleted:
        try:
            smclient.describe_domain(DomainId=domain_id)
        except smclient.exceptions.ResourceNotFound:
            logging.info(f"Deleted domain {domain_id}")
            deleted = True
            break
        time.sleep(5)
    return response


def update_domain(domain_id, default_user_settings):
    response = smclient.update_domain(
        DomainId=domain_id,
        DefaultUserSettings=default_user_settings,
    )
    updated = False
    time.sleep(0.2)
    while not updated:
        response = smclient.describe_domain(DomainId=domain_id)
        if response["Status"] == "InService":
            updated = True
        else:
            logging.info("Updating domain %s.. %s", domain_id, response["Status"])
        time.sleep(5)
    return response
