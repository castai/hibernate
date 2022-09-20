import logging
import time

import requests
from requests import Session


class NetworkError(Exception):
    pass


def get_castai_policy(clusterid, castai_apitoken):
    url = "https://api.cast.ai/v1/kubernetes/clusters/{}/policies".format
    header_dict = {"accept": "application/json",
                   "X-API-Key": castai_apitoken}

    resp = requests.get(url=url(clusterid), headers=header_dict)
    if resp.status_code == 200:
        return resp.json()


def set_castai_policy(cluster_id, castai_api_token, updated_policies):
    url = "https://api.cast.ai/v1/kubernetes/clusters/{}/policies".format
    header_dict = {"accept": "application/json",
                   "X-API-Key": castai_api_token}

    resp =  requests.put(url=url(cluster_id), json=updated_policies, headers=header_dict)
    if resp.status_code == 200:
        return resp.json()


def toggle_unschedulable_pod_policy_enabled(cluster_id: str, castai_api_token: str, policy_value: bool):
    """" Disable CAST autoscaler to prevent adding new nodes automatically"""

    current_policies = get_castai_policy(cluster_id, castai_api_token)

    if current_policies["unschedulablePods"]["enabled"] != policy_value:
        logging.info("Update policy. mismatch")
        logging.info(f'Current: {current_policies["unschedulablePods"]["enabled"]}  Future: {policy_value}')

        current_policies["unschedulablePods"]["enabled"] = policy_value

        validate_policies = set_castai_policy(cluster_id, castai_api_token, current_policies)
        if validate_policies['unschedulablePods']["enabled"] == policy_value:
            logging.info("Update completed")
            return True
        else:
            logging.info("Update failed")
            return False
    else:
        logging.info("skip policy update")
        return True


def create_hibernation_node(cluster_id: str, castai_api_token: str, instance_type: str, k8s_taint: str, cloud: str):
    """ Create Node with Taint that will stay running during hibernation"""
    url = "https://api.cast.ai/v1/kubernetes/external-clusters/{}/nodes".format
    header_dict = {"accept": "application/json",
                   "X-API-Key": castai_api_token}

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
                logging.info("ops_response: %s" % ops_response)
                break
            time.sleep(60)
        return nodeId


def delete_all_pausable_nodes(cluster_id: str, castai_api_token: str, hibernation_node_id):
    """" Delete all nodes through CAST AI mothership excluding hibernation node"""
    url = "https://api.cast.ai/v1/kubernetes/external-clusters/{}/nodes".format
    header_dict = {"accept": "application/json",
                   "X-API-Key": castai_api_token}

    with Session() as session:
        try:
            with session.get(url=url(cluster_id), headers=header_dict) as resp:
                resp.raise_for_status()
                node_list_result = resp.json()
        except Exception as e:
            raise NetworkError('Failed to get Nodes list') from e

        urlDelete = "https://api.cast.ai/v1/kubernetes/external-clusters/{}/nodes/{}".format
        paramsDelete = {
            "forceDelete": True,
            "drainTimeout": 60
        }
        for node in node_list_result["items"]:
            # drain/delete each node
            if node["id"] == hibernation_node_id:
                logging.info("Skipping temp node: %s " % node["id"])
            else:
                logging.info("Deleting: %s with id: %s" % (node["name"], node["id"]))
                try:
                    with session.delete(url=urlDelete(cluster_id, node["id"]), headers=header_dict,
                                        params=paramsDelete) as deleteresp:
                        deleteresp.raise_for_status()
                        delete_node_result = deleteresp.json()
                        logging.info(delete_node_result)
                except Exception as e:
                    raise NetworkError(f'Failed to delete node {delete_node_result}') from e
