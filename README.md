# Hibernate shrinks and expands your cluster on schedule

This utility currently is on best effort support by @Leon Kuperman and @Augustinas Stirbis through community slack

### Install hibernate

Run this command to install Hibernate CronJobs

```shell
kubectl apply -f https://raw.githubusercontent.com/castai/hibernate/main/deploy.yaml
```

### Change API key

Create API token with Full Access permissions and encode base64

```shell
echo -n "98349587234524jh523452435kj2h4k5h2k34j5h2kj34h5k23h5k2345jhk2" | base64
```

use this value to update Secret

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: castai-Hibernate
  namespace: castai-agent
type: Opaque
data:
  API_KEY: >-
    CASTAI-API-KEY-REPLACE-ME-WITH-ABOVE==
```
 
OR for convenience use one liner

```shell
kubectl get secret castai-hibernate -n castai-agent -o json | jq --arg API_KEY "$(echo -n 9834958-CASTAI-API-KEY-REPLACE-ME-5k2345jhk2 | base64)" '.data["API_KEY"]=$API_KEY' | kubectl apply -f -
```

### Set Schedule 

Modify the `.spec.schedule` parameter for the Hibernate-pause and Hibernate-resume cronjobs according to  [this syntax](https://kubernetes.io/docs/concepts/workloads/controllers/cron-jobs/#schedule-syntax). Beginning with Kubernetes v1.25 and later versions, it is possible to define a time zone for a CronJob by assigning a valid time zone name to `.spec.timeZone`. For instance, by assigning `.spec.timeZone: "Etc/UTC"`, Kubernetes will interpret the schedule with respect to Coordinated Universal Time (UTC). To access a list of acceptable time zone options, please refer to the following link: [List of Valid Time Zones](https://en.wikipedia.org/wiki/List_of_tz_database_time_zones).


### Set API URL

If you need to use a different API URL (e.g. europe for example), you can provide the URL via environment variable:

```
API_URL = https://api.eu.cast.ai
```

Default is https://api.cast.ai


## How it works

Hibernate-pause Job will 
 - Disable Unscheduled Pod Policy (to prevent growing cluster)
 - Prepare Hibernation node (node that will stay hosting essential components)
 - Mark essential Deployments with Hibernation toleration (system critical and with NAMESPACES_TO_KEEP env var)
 - Delete all other nodes (only hibernation node should stay running)

Hibernate-resume Job will
 - Renable Unscheduled Pod Policy to allow cluster to expand to needed size

Override default hibernate-node size
 - Set the HIBERNATE_NODE environment variable to override the default node sizing selections. Make sure the size selected is appropriate for your cloud. 

Override default NAMESPACES_TO_KEEP
 - Set the NAMESPACES_TO_KEEP environment variable to override, "opa,istio"" 

Override default "PROTECT_EVICTION_DISABLED" and set to "true" to prevent the removal of removal-disabled nodes from being removed during hibernate. This looks for the `autoscaling.cast.ai/removal-disabled="true"` label on a node and if it exists excludes it from being cordoned and deleted.

# Development

## Create [aks|eks|gke] K8s cluster 
- create file hack/{cloud}/local.auto.tfvars from example, if already have check cluster name
- run "make aks|eks|gke" to create cluster
- connect to cluster (az|gcloud|aws) - or best way go to cluster page in cloud and click connect / switch kubectl contex

## Run code locally
- copy cluster_id from console.cast.ai to .env file (example .env.example)
- uncomment in main.py # local_development = True
- manually create configMap object

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: castai-hibernate-state
  namespace: castai-agent
```

- run end2end tests

## Live test and release
### should be automated, but this project will be sunset soon

- modify Makefile to change tags, bump version and rename latest to test, build locally container and push to registry, test this version as smoke test
- merge PR to main
- change back tag test to latest and push to registry
