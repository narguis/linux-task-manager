.PHONY: run test check deb install uninstall

run:
	python3 -m linux_task_manager

test:
	python3 -m unittest discover -s tests -v

check: test
	python3 -m compileall -q linux_task_manager

deb:
	./packaging/build-deb.sh

install:
	./install.sh

uninstall:
	./uninstall.sh
