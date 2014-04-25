all::	build
build::	protobuf dist
dist::	dist-app
clean::	clean-py clean-proto clean-dist

DOT := \033[34m●\033[39m
TICK := \033[32m✔\033[39m

PYTHON_REQ := CPython>=2.7,<3

clean-py:
	find ./src/ddocker -name "*.py[co]" -exec rm {} \;

clean-proto:
	rm -rf ./src/ddocker/proto/*_pb2.py

clean-dist:
	rm -rf .pants.run
	rm -rf .pants.d
	rm -rf ./dist

protobuf: clean-proto
	@echo "$(DOT) Building python proto modules."
	protoc ./proto/*.proto --python_out=./src/ddocker/
	@echo "$(TICK) Building python proto modules."

dist-app: protobuf
	@echo "$(DOT) Building ddocker distribution binary."
	./bin/pants build -i '$(PYTHON_REQ)' src/ddocker/app:ddocker
	@echo "$(TICK) Building ddocker distribution binary."
