import pathlib

p = pathlib.Path("demo.py")
s = p.read_text(encoding="utf-8")

old_table = '''table = f"""
   {"\\n".join(f"  - {k}: {v!r}" for k, v in user.items())}
"""
print("   f-string 跨行 + 表达式内反斜杠：")
print(table)'''
new_table = '''table = f"""用户信息：
{
    "\\n".join(
        f"  - {k}: {v!r}"
        for k, v in user.items()
    )
}"""
print("   f-string 表达式可以跨行书写：")
print(table)'''
assert old_table in s, "table block not found"
s = s.replace(old_table, new_table)

old_b = '''stream = [11, 12, 13, 14, 15]
print("4) itertools.batched(2):", list(itertools.batched(stream, 2)))
try:
    list(itertools.batched(stream, 2, strict=True))
except ValueError as exc:
    print("   strict=True 时长度不整除会报错:", exc)'''
new_b = '''stream = [11, 12, 13, 14, 15]
print("4) itertools.batched(2):", list(itertools.batched(stream, 2)))
print("   不足一整批的尾巴单独成组:", list(itertools.batched("ABCDEFG", 3)))
# 备注：batched(..., strict=True) 是 Python 3.13 才加入的参数，3.12 里只有 (iterable, n)'''
assert old_b in s, "batched block not found"
s = s.replace(old_b, new_b)

s = s.replace(
    "  * PEP 701 —— f-string 全面升级（可嵌套同种引号、可跨行、表达式中可含反斜杠）",
    "  * PEP 701 —— f-string 全面升级（可嵌套同种引号、表达式可跨行、可含反斜杠与注释）",
)

p.write_text(s, encoding="utf-8")
print("patched ok")
