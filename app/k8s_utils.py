import logging
from kubernetes.client.rest import ApiException


class K8sAPIError(Exception):
    pass


def cordon_all_nodes(client, exclude_node_id: str):
    """cordon all the nodes so essential components could be scheduled only on hybernation node"""
    logging.info("Cordon function")

    node_body = {
        "spec": {
            "unschedulable": True
        }
    }

    node_list = client.list_node()
    for node in node_list.items:
        logging.info("Inspecting node %s to cordon", node.metadata.name)
        if node.metadata.labels.get("provisioner.cast.ai/node-id") != exclude_node_id:
            logging.info("Cordoning: %s" % node.metadata.name)
            client.patch_node(node.metadata.name, node_body)
        else:
            logging.info("skip Cordoning node: %s" % node.metadata.name)


def add_special_tolerations(client, namespace: str, toleration: str):
    """" modify essential deployment to keep them running on hibernation node (tolerate node)"""
    logging.info("add tolerations to essential workloads function")

    toleration_to_add = {
        'key': toleration,
        'effect': 'NoSchedule',
        'operator': 'Exists'
    }

    cast_deployment_list = client.list_namespaced_deployment(namespace)
    logging.info("deployments found %s", len(cast_deployment_list.items))
    for deployment in cast_deployment_list.items:
        deployment_name = deployment.metadata.name
        logging.info("Patching and restarting: %s" % deployment_name)
        current_tolerations = deployment.spec.template.spec.tolerations

        if current_tolerations is None:
            current_tolerations = []
        current_tolerations.append(toleration_to_add)

        restart_body = {
            'spec': {
                'template': {
                    'spec': {
                        'tolerations': current_tolerations
                    }
                }
            }
        }

        patch_result = None
        try:
            patch_result = client.patch_namespaced_deployment(deployment_name, namespace, restart_body)
        except ApiException as e:
            raise K8sAPIError(
                f'Exception when calling AppsV1Api->patch_namespaced_deployment: {deployment_name}') from e

        if patch_result:
            logging.info("Patch complete...")


def hibernation_node_already_exist(client, taint: str, k8s_label: str):
    """" Node with hibernation taint already exist """
    node_list = client.list_node(label_selector=k8s_label)
    for node in node_list.items:
        if node.spec.taints:
            for current_taint in node.spec.taints:
                if current_taint.to_dict()["key"] == taint:
                    logging.info("found hibernation compatible node with label %s and taint %s", k8s_label, taint)
                    return node.metadata.labels.get("provisioner.cast.ai/node-id")


def azure_system_node(client, k8s_label: str, taint: str):
    """ mark existing AKS system node with hibernation Taint if small system node is found"""

    node_list = client.list_node(label_selector=k8s_label)
    hibernation_node = None

    if len(node_list.items) > 0:
        for any_node in node_list.items:
            if int(any_node.status.capacity["cpu"]) == 2:
                logging.info("Found Node with 2 CPU %s", any_node.metadata.name)
                hibernation_node = any_node
                break

    if hibernation_node:
        taint_to_add = {"key": taint, "effect": "NoSchedule"}
        logging.info("found single system nodes, will add taint")

        current_taints = hibernation_node.spec.taints
        if current_taints is None:
            current_taints = []
        current_taints.append(taint_to_add)

        taint_body = {
            "spec": {
                "taints": current_taints
            },
            "metadata": {
                "labels": {
                    "scheduling.cast.ai/paused-cluster": "true",
                    "scheduling.cast.ai/spot-fallback": "true",
                    "scheduling.cast.ai/spot": "true"
                }
            }
        }

        logging.info("patching node %s with taint", hibernation_node.metadata.name)
        patch_result = None
        try:
            patch_result = client.patch_node(hibernation_node.metadata.name, taint_body)
        except ApiException as e:
            raise K8sAPIError(f'Failed to taint node {hibernation_node.metadata.name}') from e

        if patch_result:
            logging.info("node %s successfully patched", hibernation_node.metadata.name)
            return hibernation_node.metadata.labels["provisioner.cast.ai/node-id"]
