from pathlib import Path


# 每个原始业务文件必须有且仅有一份 metadata；
# 后续每个 chunk 都会继承这里的业务标签，用于 filter 检索。
DOCUMENT_METADATA: dict[str, dict] = {
    "上海口岸空运出口报关品名清单.pdf": {
        "business_line": "air_export",
        "category": "customs",
        "sub_category": "shanghai_port_cargo_name_list",
        "doc_type": "pdf",
        "applicable_to": ["air_export", "shanghai_port"],
        "keywords": ["上海口岸", "空运出口", "报关", "品名清单"],
        "is_form": False,
        "port": "shanghai",
        "version": "v1",
    },
    "危险品包括锂电池货物交运授权委托书.docx": {
        "business_line": "air_export",
        "category": "dangerous_goods",
        "sub_category": "dangerous_goods_authorization",
        "doc_type": "docx",
        "applicable_to": ["dangerous_goods", "lithium_battery"],
        "keywords": ["危险品", "锂电池", "交运", "授权委托书"],
        "is_form": True,
        "port": None,
        "version": "v1",
    },
    "符合包装说明第Ⅱ部分锂电池货物收运检查单（适用于托运人交运货物）.docx": {
        "business_line": "air_export",
        "category": "dangerous_goods",
        "sub_category": "lithium_battery_acceptance_checklist_shipper",
        "doc_type": "doc",
        "applicable_to": ["lithium_battery", "shipper"],
        "keywords": ["锂电池", "收运检查单", "托运人", "包装说明第Ⅱ部分"],
        "is_form": True,
        "port": None,
        "version": "v1",
    },
    "符合包装说明第Ⅱ部分锂电池货物收运检查单（适用于销售代理人交运货物）.docx": {
        "business_line": "air_export",
        "category": "dangerous_goods",
        "sub_category": "lithium_battery_acceptance_checklist_agent",
        "doc_type": "doc",
        "applicable_to": ["lithium_battery", "sales_agent"],
        "keywords": ["锂电池", "收运检查单", "销售代理人", "包装说明第Ⅱ部分"],
        "is_form": True,
        "port": None,
        "version": "v1",
    },
    "符合包装说明第Ⅱ部分锂电池货物运输声明（适用于托运人交运货物）.docx": {
        "business_line": "air_export",
        "category": "dangerous_goods",
        "sub_category": "lithium_battery_declaration_shipper",
        "doc_type": "doc",
        "applicable_to": ["lithium_battery", "shipper"],
        "keywords": ["锂电池", "运输声明", "托运人", "包装说明第Ⅱ部分"],
        "is_form": True,
        "port": None,
        "version": "v1",
    },
    "符合包装说明第Ⅱ部分锂电池货物运输声明（适用于销售代理人交运货物）.docx": {
        "business_line": "air_export",
        "category": "dangerous_goods",
        "sub_category": "lithium_battery_declaration_agent",
        "doc_type": "doc",
        "applicable_to": ["lithium_battery", "sales_agent"],
        "keywords": ["锂电池", "运输声明", "销售代理人", "包装说明第Ⅱ部分"],
        "is_form": True,
        "port": None,
        "version": "v1",
    },
    "货物交运授权委托书（普货不带电版）.docx": {
        "business_line": "air_export",
        "category": "general_cargo",
        "sub_category": "general_cargo_authorization",
        "doc_type": "docx",
        "applicable_to": ["general_cargo", "non_battery"],
        "keywords": ["普货", "不带电", "授权委托书", "交运"],
        "is_form": True,
        "port": None,
        "version": "v1",
    },
    "附件1-ACCOS系统分单件数录入要求.pptx": {
        "business_line": "air_export",
        "category": "operations",
        "sub_category": "accos_piece_count_entry",
        "doc_type": "pptx",
        "applicable_to": ["operations", "accos"],
        "keywords": ["ACCOS", "分单件数", "录入要求", "系统操作"],
        "is_form": False,
        "port": None,
        "version": "v1",
    },
}


# 运行时使用：负责“取数据”，在处理每个文档时调用。
def get_metadata(filename: str) -> dict:
    key = Path(filename).name
    if key not in DOCUMENT_METADATA:
        raise KeyError(f"未找到文件 metadata 配置: {key}")
    return DOCUMENT_METADATA[key].copy()


# 开发/部署时使用：负责“查问题”，提前发现配置错误。
def validate_metadata(doc_dir: str | None = None) -> None:
    if not doc_dir:
        return

    # 双向校验：
    # 1. docs 目录里的文件必须有 metadata
    # 2. metadata 里声明的文件也必须真实存在
    missing = []
    files = [path for path in sorted(Path(doc_dir).glob("*")) if path.is_file()]
    for path in files:
        if path.is_file() and path.name not in DOCUMENT_METADATA:
            missing.append(path.name)
    if missing:
        raise ValueError(f"以下文件缺少 metadata 配置: {', '.join(missing)}")
    unknown = sorted(set(DOCUMENT_METADATA) - {path.name for path in files})
    if unknown:
        raise ValueError(f"metadata 配置存在不存在的文件: {', '.join(unknown)}")
