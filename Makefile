.PHONY: help build verify test stats install

help:
	@echo "labor-law-cn 常用命令："
	@echo "  make build    重建索引（data/index.json 等）"
	@echo "  make verify   校验语料完整性"
	@echo "  make test     运行冒烟测试"
	@echo "  make stats    查看语料规模"
	@echo "  make install  安装到 ~/.claude/skills/labor-law-cn"
	@echo "  make search Q='加班费 --status 有效'   检索"

build:
	python3 scripts/build_index.py

verify:
	python3 scripts/verify.py

test:
	python3 tests/test_smoke.py

stats:
	python3 scripts/search.py --stats

install:
	bash scripts/install.sh

search:
	python3 scripts/search.py $(Q)
