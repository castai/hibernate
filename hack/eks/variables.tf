variable "castai_api_token" {
  type        = string
  description = "CAST.AI api token"
}

variable "aws_access_key_id" {
  type        = string
  description = "Your own access key id for operating terraform"
}

variable "aws_secret_access_key" {
  type        = string
  description = "Your own access key secret for operating terraform"
}

variable "cluster_region" {
  type        = string
  description = "AWS region your cluster is located."
  default     = "eu-central-1"
}

variable "cluster_name" {
  type        = string
  description = "EKS cluster name in AWS account."
  default     = "shrink-cluster-august"
}

variable "tags" {
  type        = map(any)
  description = "Optional tags for new cluster nodes. This parameter applies only to new nodes - tags for old nodes are not reconciled."
  default     = {}
}

variable "delete_nodes_on_disconnect" {
  type        = bool
  description = "Optional parameter, if set to true - CAST AI provisioned nodes will be deleted from EC2 on cluster disconnection."
  default     = false
}