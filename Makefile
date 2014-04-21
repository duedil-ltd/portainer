all::	clean setup build
build::	protobuf dist
dist::	dist-cli dist-executor
clean::	clean-py clean-env

setup:
	@./bin/setup

clean-env:
	@echo "\033[34m●\033[39m Deleting virtual environment."
	rm -rf ./bin/env
	@echo "\033[32m✔\033[39m Deleting virtual environment."

clean-py:
	@echo "\033[34m●\033[39m Deleting python compiled files."
	find ./ddocker -name "*.py[co]" -exec rm {} \;
	@echo "\033[32m✔\033[39m Deleting python compiled files."

protobuf:
	@echo "\033[34m●\033[39m Building python proto modules."
	protoc proto/*.proto --python_out=ddocker/
	touch ddocker/proto/__init__.py
	@echo "\033[32m✔\033[39m Building python proto modules."

dist-cli:
	@echo "\033[34m●\033[39m Building ddocker distribution binary."
	@echo "\033[32m✔\033[39m Building ddocker distribution binary."

dist-executor:
	@echo "\033[34m●\033[39m Building ddocker executor."
	@echo "\033[32m✔\033[39m Building ddocker executor."
