import logging
import os
import sys
import time
from app import main
from cast_utils import get_cluster_status
from utils import basic_retry, step

logger = logging.getLogger()
logger.setLevel(level=logging.INFO)
handler = logging.StreamHandler(sys.stdout)
handler.setLevel(logging.DEBUG)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
handler.setFormatter(formatter)
logger.addHandler(handler)


class Scenario:
    @step
    @basic_retry(attempts=2, pause=5)
    def cluster_is_ready(self):
        cluster = get_cluster_status(main.cluster_id, main.castai_api_token)
        logging.info(f"TEST cluster status: {cluster.get('status')}, id: {cluster.get('id')}")
        assert cluster.get('status') == 'ready'

    @step
    def suspend(self):
        logging.info(f"TEST suspending cluster")
        main.handle_suspend()
        hibernation_node_id = main.hibernation_node_already_exist(client=main.k8s_v1,
                                                                  taint=main.castai_pause_toleration,
                                                                  k8s_label=main.cloud_labels[main.cloud])
        logging.info(f"TEST hibernation node found after cluster suspend: {hibernation_node_id}")
        # TODO: https://castai.atlassian.net/browse/CORE-2796 (uncomment when regression fixed https://castai.atlassian.net/browse/CORE-2796)
        # assert hibernation_node_id

    @step
    def resume(self):
        logging.info(f"TEST resuming cluster")
        main.handle_resume()
        policy_json = main.get_castai_policy(main.cluster_id, main.castai_api_token)
        assert policy_json["unschedulablePods"]["enabled"]


def test_all():
    logging.info("TEST AKS test started")
    scenario = Scenario()

    scenario.cluster_is_ready()
    scenario.suspend()
    time.sleep(35)
    scenario.cluster_is_ready()
    time.sleep(35)
    scenario.resume()
    scenario.cluster_is_ready()
