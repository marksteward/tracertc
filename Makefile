.PHONY: build run lock

build:
	docker build -t tracertc .

run:
	docker run --rm -ti --name tracertc --net host tracertc poetry run python tracertc.py

lock:
	docker run --rm -ti -v $$PWD:/app tracertc poetry lock

