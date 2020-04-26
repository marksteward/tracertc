.PHONY: build run lock

build:
	docker build -t tracertc .

run:
	docker run --rm -ti --name tracertc --net host tracertc poetry run python server.py

dev:
	docker run --rm -ti --name tracertc --net host -v $$PWD:/app tracertc poetry run python server.py

lock:
	docker run --rm -ti -v $$PWD:/app tracertc poetry lock

