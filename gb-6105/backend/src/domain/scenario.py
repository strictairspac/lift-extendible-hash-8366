from .certificates import parse, validate
from .inspection import inspect

CONFIG = {
    "title": "榆梯检点·证书哈希目录",
    "team": "榆梯维保复核组（11 人）",
    "description": "复核工位用证书编号检出归档记录，追查桶分裂及缺失、到期、撤销的证书。",
    "direction": "存储引擎 / 可扩展哈希",
    "mechanism": "Python 依据哈希低位寻址，按局部深度拆桶，必要时倍增目录。",
    "modules": ["检证接班", "资质卷宗", "目录重放", "检证与桶证据"],
    "unit": "检证交接批",
    "max_parameter": 16,
    "parameter_label": "目标单桶容量",
    "default_parameter": 2,
    "facts": ["目录槽位", "桶分裂", "异常检证"],
    "palette": 5,
    "fixture": "YT-1124-东梯检",
}


def cert(code, expires, revoked=False):
    return {"code": f"YT-Q{code:02d}", "lift": f"YT-L{code:02d}", "expires_on": expires, "revoked": revoked}


CERTIFICATES = [
    cert(1, "2026-12-01"), cert(2, "2026-12-01"), cert(3, "2026-11-24"),
    cert(4, "2026-11-20"), cert(5, "2026-12-01", True), cert(6, "2026-12-24"),
    cert(7, "2026-12-05"), cert(8, "2026-12-31"), cert(9, "2026-12-05"),
]

FIXTURES = [
    {
        "code": "YT-1124-EAST", "title": "YT-1124-东梯检", "description": "档案入九件，点查六件。",
        "payload": {"certificates": CERTIFICATES, "review_date": "2026-11-24",
                    "probes": ["YT-Q01", "YT-Q03", "YT-Q04", "YT-Q05", "YT-Q07", "YT-Q99"]},
    },
    {
        "code": "YT-1124-SOUTH", "title": "南廊补位检证", "description": "巡检日为失效日前一天，证书仍有效。",
        "payload": {"certificates": CERTIFICATES[:4], "review_date": "2026-11-23",
                    "probes": ["YT-Q01", "YT-Q03", "YT-Q04"]},
    },
]


def run(payload, parameter, db):
    if type(parameter) is not int or not 1 <= parameter <= 16:
        raise ValueError("目标单桶容量须为 1–16")
    certs, probes, review_date = parse(payload)
    directory, unavailable, rows = inspect(certs, probes, review_date, parameter)
    return {
        "summary": f"目录装载 {len(certs)} 条证书，分裂 {directory.splits} 次，点查 {len(probes)} 条发现 {unavailable} 条异常。",
        "metrics": {"目录槽位": len(directory.slots), "桶分裂": directory.splits, "异常检证": unavailable},
        "rows": rows,
    }
