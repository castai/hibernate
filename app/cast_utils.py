import logging
import time
from utils import basic_retry
import requests
from requests import Session


class NetworkError(Exception):
    pass


@basic_retry(attempts=3, pause=5)
def get_cluster_status(clusterid, castai_apitoken):
    url = "https://api.cast.ai/v1/kubernetes/external-clusters/{}".format
    header_dict = {"accept": "application/json",
                   "X-API-Key": castai_apitoken}

    resp = requests.get(url=url(clusterid), headers=header_dict)
    if resp.status_code == 200:
        return resp.json()


@basic_retry(attempts=3, pause=5)
def cluster_ready(clusterid, castai_apitoken):
    cluster = get_cluster_status(clusterid, castai_apitoken)
    logging.info(f"TEST cluster status: {cluster.get('status')}, id: {cluster.get('id')}")
    if cluster.get('status') == 'ready':
        return True
    return False


def get_castai_policy(cluster_id, castai_api_token):
    url = "https://api.cast.ai/v1/kubernetes/clusters/{}/policies".format
    header_dict = {"accept": "application/json",
                   "X-API-Key": castai_api_token}

    resp = requests.get(url=url(cluster_id), headers=header_dict)
    if resp.status_code == 200:
        return resp.json()


def set_castai_policy(cluster_id, castai_api_token, updated_policies):
    url = "https://api.cast.ai/v1/kubernetes/clusters/{}/policies".format
    header_dict = {"accept": "application/json",
                   "X-API-Key": castai_api_token}

    resp = requests.put(url=url(cluster_id), json=updated_policies, headers=header_dict)
    if resp.status_code == 200:
        return resp.json()


@basic_retry(attempts=2, pause=5)
def toggle_autoscaler_top_flag(cluster_id: str, castai_api_token: str, policy_value: bool):
    """" Disable CAST autoscaler to prevent adding new nodes automatically"""

    current_policies = get_castai_policy(cluster_id, castai_api_token)

    if current_policies["enabled"] != policy_value:
        logging.info("Update policy. mismatch")
        logging.info(f'Current: {current_policies["enabled"]}  Future: {policy_value}')

        current_policies["enabled"] = policy_value

        validate_policies = set_castai_policy(cluster_id, castai_api_token, current_policies)
        if validate_policies["enabled"] == policy_value:
            logging.info("Update completed")
            return True
        else:
            logging.info("Update failed")
            return False
    else:
        logging.info("skip policy update")
        return True


@basic_retry(attempts=3, pause=5)
def create_hibernation_node(cluster_id: str, castai_api_token: str, instance_type: str, k8s_taint: str, cloud: str):
    """ Create Node with Taint that will stay running during hibernation"""
    url = "https://api.cast.ai/v1/kubernetes/external-clusters/{}/nodes".format
    header_dict = {"accept": "application/json",
                   "X-API-Key": castai_api_token}

    add_node_result = ""
    new_node_body = {}
    new_node_body["instanceType"] = instance_type
    if k8s_taint:
        special_taint = [{
            "effect": "NoSchedule",
            "key": k8s_taint,
            "value": "true"
        }]
        new_node_body["kubernetesTaints"] = special_taint
    if cloud == "AKS":
        new_node_body["kubernetesLabels"] = {
            "scheduling.cast.ai/paused-cluster": "true",
            "kubernetes.azure.com/mode": "system",
            "scheduling.cast.ai/spot-fallback": "true",
            "scheduling.cast.ai/spot": "true"
        }
    else:
        new_node_body["kubernetesLabels"] = {
            "scheduling.cast.ai/paused-cluster": "true",
            "scheduling.cast.ai/spot-fallback": "true",
            "scheduling.cast.ai/spot": "true"
        }

    with Session() as session:
        try:
            with session.post(url=url(cluster_id), json=new_node_body, headers=header_dict) as postresp:
                postresp.raise_for_status()
                add_node_result = postresp.json()
        except Exception as e:
            raise NetworkError(f'Failed to add node {add_node_result}') from e

        # wait for new node to be created, listen to operation
        ops_id = add_node_result["operationId"]
        nodeId = add_node_result["nodeId"]
        urlOperations = "https://api.cast.ai/v1/kubernetes/external-clusters/operations/{}".format
        done_node_creation = False

        while not done_node_creation:
            logging.info("checking node creation operation ID: %s", ops_id)
            try:
                with session.get(url=urlOperations(ops_id), headers=header_dict) as operation:
                    operation.raise_for_status()
                    ops_response = operation.json()
            except Exception as e:
                raise NetworkError('Failed to get Operation status') from e

            if ops_response["done"]:
                logging.info(f"ops_response: {ops_response}")
                if ops_response.get('error'):
                    raise NetworkError('Failed to get Operation status')
                break
            time.sleep(60)
        return nodeId


@basic_retry(attempts=4, pause=15)
def delete_all_pausable_nodes(cluster_id: str, castai_api_token: str, hibernation_node_id: str,
                              protect_removal_disabled: str, job_node_id=None):
    """" Delete all nodes through CAST AI mothership excluding hibernation node"""
    node_list_result = get_castai_nodes(cluster_id, castai_api_token)
    for node in node_list_result["items"]:
        # drain/delete each node
        if node["id"] == hibernation_node_id or node["id"] == job_node_id:
            logging.info("Skipping temp node: %s " % node["id"])
            continue
        if node["labels"].get("autoscaling.cast.ai/removal-disabled") == "true" and protect_removal_disabled == "true":
            logging.info("Skipping node protected by removal-disabled ID: %s " % node["id"])
            continue
        logging.info("Deleting: %s with id: %s" % (node["name"], node["id"]))
        delete_castai_node(cluster_id, castai_api_token, node["id"])


def get_castai_nodes_by_instance_type(cluster_id: str, castai_api_token: str, instance_type: str):
    """" Get all nodes by instance type"""
    node_list_result = get_castai_nodes(cluster_id, castai_api_token)
    nodes = []
    for node in node_list_result["items"]:
        if node["instanceType"] == instance_type and node["state"]["phase"] == "ready":
            nodes.append(node)
    logging.info("Found %s nodes with instance type: %s" % (len(nodes), instance_type))
    return nodes


def get_suitable_hibernation_node(cluster_id: str, castai_api_token: str, instance_type: str, cloud: str):
    cast_nodes = get_castai_nodes_by_instance_type(cluster_id, castai_api_token, instance_type=instance_type)
    for node in sorted(cast_nodes, key=lambda k: k['createdAt']):
        if node["labels"].get("scheduling.cast.ai/paused-cluster") == "true":
            if cloud == "AKS":  # Azure special case use system node
                if node["labels"].get("kubernetes.azure.com/mode") == "system":
                    logging.info("Suitable system node found: %s" % node["name"])
                    return node["name"]
            else:
                logging.info("Suitable node found: %s" % node["name"])
                return node["name"]


def get_castai_nodes(cluster_id, castai_api_token):
    """ Get all nodes from CAST AI API inside the cluster"""
    url = "https://api.cast.ai/v1/kubernetes/external-clusters/{}/nodes".format
    header_dict = {"accept": "application/json",
                   "X-API-Key": castai_api_token}

    resp = requests.get(url=url(cluster_id), headers=header_dict)
    if resp.status_code == 200:
        return resp.json()


def get_castai_node_name_by_id(cluster_id, castai_api_token, node_id):
    """ Get node by CAST AI id from CAST AI API"""
    url = "https://api.cast.ai/v1/kubernetes/external-clusters/{}/nodes/{}".format
    header_dict = {"accept": "application/json",
                   "X-API-Key": castai_api_token}

    resp = requests.get(url=url(cluster_id, node_id), headers=header_dict)
    if resp.status_code == 200:
        if resp.json()['name']:
            return resp.json()['name']
        else:
            return False


@basic_retry(attempts=3, pause=30)
def delete_castai_node(cluster_id, castai_api_token, node_id):
    """ Delete single node"""
    url = "https://api.cast.ai/v1/kubernetes/external-clusters/{}/nodes/{}".format
    header_dict = {"accept": "application/json",
                   "X-API-Key": castai_api_token}
    paramsDelete = {
        "forceDelete": True,
        "drainTimeout": 60
    }

    resp = requests.delete(url=url(cluster_id, node_id), headers=header_dict, params=paramsDelete)
    if resp.status_code == 200:
        delete_node_result = resp.json()
        logging.info(delete_node_result)
        return True
    else:
        return False


def get_cluster_details(cluster_id, castai_api_token):
    url = "https://api.cast.ai/v1/kubernetes/external-clusters/{}".format
    header_dict = {"accept": "application/json",
                   "X-API-Key": castai_api_token}

    resp = requests.get(url=url(cluster_id), headers=header_dict)
    if resp.status_code == 200:
        return resp.json()
