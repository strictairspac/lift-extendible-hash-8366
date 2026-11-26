from .hash_directory import Directory


def inspect(certificates, probes, review_date, capacity):
    directory = Directory(capacity)
    for certificate in certificates:
        directory.add(certificate)
    rows = []
    unavailable = 0
    for code in probes:
        bucket, cert = directory.locate(code)
        verdict = cert.verdict(review_date) if cert else "未登记"
        unavailable += verdict != "有效"
        rows.append({
            "类别": "检证请求", "项目": code, "桶号": bucket.number, "局部深度": bucket.depth,
            "桶内条数": len(bucket.records), "电梯或槽位": cert.lift if cert else None,
            "结论": verdict,
        })
    for bucket in directory.buckets():
        spill = max(0, len(bucket.records) - capacity)
        rows.append({
            "类别": "目录追踪", "项目": f"B{bucket.number:03d}", "桶号": bucket.number, "局部深度": bucket.depth,
            "桶内条数": len(bucket.records), "电梯或槽位": f"{1 << (directory.depth - bucket.depth)} 个目录槽位",
            "结论": f"深度封顶，溢出 {spill} 条" if spill else "容量内",
        })
    return directory, unavailable, rows
