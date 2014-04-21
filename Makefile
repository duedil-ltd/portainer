all::   clean setup
clean:: clean-py clean-env

setup:
	@./bin/setup

clean-env:
	@echo "Deleting virtual environment."
	@rm -rf ./bin/env

clean-py:
	@echo "Deleting python compiled files."
	@find ./ddocker -name "*.py[co]" -exec rm {} \;

protobuf:
	@echo "Building python proto files"
	protoc proto/*.proto --python_out=ddocker/
	@touch ddocker/proto/__init__.py
