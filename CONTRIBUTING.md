# 贡献指南

欢迎补充法规、修正元数据、改进检索脚本。

## 数据贡献

1. 只使用**官方来源**（国家法律法规数据库、人社部、中国政府网、地方政府门户）；
2. 在 `data/<层级>/` 下新增 Markdown，front matter 必须符合 [`SCHEMA.md`](SCHEMA.md)；
3. 正文保持官方原文，不改写条文；版式归一化规则见 `scripts/docx2md.py`；
4. 运行 `python3 scripts/build_index.py && python3 scripts/verify.py`，确保 0 error；
5. 在 PR 中说明来源 URL、抓取日期、时效性依据。

## 代码贡献

- Python 3.10+，仅使用标准库 + PyYAML（抓取脚本可选 bs4）；
- 保持 `search.py` 的 CLI 向后兼容；
- 新增过滤维度时同步更新 `docs/00-使用指南.md` 与 `SKILL.md`；
- 运行 `pytest -q` 通过。

## 提交信息

```
data: add <法规名称> (<公布日期>)
fix: correct effective date for <法规>
feat: add --age filter to search.py
docs: ...
```

## 不同意的内容

如认为某条法规状态/日期有误，请附官方链接与截图/文本依据；以官方最新公布为准。

## 许可

贡献即同意以 CC BY 4.0（数据/文档）与 MIT（代码）许可发布。
