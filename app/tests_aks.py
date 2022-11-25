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
    # def __init__(self):
    #     load_dotenv()
    #     self.castai_api_token = os.environ["API_KEY"]
    #     self.cluster_id = os.environ["CLUSTER_ID"]
    #     self.hibernate_node_type = os.environ["HIBERNATE_NODE"]
    #     self.cloud = os.environ["CLOUD"]
    #     self.action = os.environ["ACTION"]
    #     self.my_node_name = os.environ.get("MY_NODE_NAME")

    @step
    @basic_retry(attempts=2, pause=5)
    def cluster_is_ready(self):
        cluster = get_cluster_status(main.cluster_id, main.castai_api_token)
        logging.info(f"cluster status: {cluster.get('status')}, id: {cluster.get('id')}")
        assert cluster.get('status') == 'ready'

    @step
    def suspend(self):
        logging.info(f"suspending cluster")
        main.handle_suspend()
        hibernation_node_id = main.hibernation_node_already_exist(client=main.k8s_v1, taint=main.castai_pause_toleration,
                                                             k8s_label=main.cloud_labels[main.cloud])
        logging.info(f"hibernation node found after cluster suspend: {hibernation_node_id}")
        assert hibernation_node_id


def test_all():
    logging.info("AKS test started")

    scenario = Scenario()

    scenario.cluster_is_ready()
    scenario.suspend()
    time.sleep(10)
    scenario.cluster_is_ready()

