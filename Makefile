default: release

APP="castai/hibernator"
TAG_LATEST=$(APP):latest

gke:
	(cd ./hack/gke && terraform init && terraform apply -auto-approve)

eks:
	(cd ./hack/gke && terraform init && terraform apply -target module.vpc -auto-approve && terraform apply -target module.eks -auto-approve && terraform apply -auto-approve)

pull:
	docker pull $(TAG_LATEST)

build:
	@echo "==> Building hibernator container"
	docker build --cache-from $(TAG_LATEST) --platform linux/amd64 -t $(TAG_LATEST) .

publish:
	@echo "==> pushing to docker hub"
	docker push $(TAG_LATEST)

release: pull
release: build
release: publish

deploy:
	kubectl apply -f deploy.yaml