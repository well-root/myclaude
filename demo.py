"""Python 3.12 新特性演示。

覆盖以下 PEP：
  * PEP 695 —— 新的泛型语法 ``def f[T](...)`` / ``class C[T]`` 以及 ``type`` 类型别名语句
  * PEP 701 —— f-string 全面升级（可嵌套同种引号、表达式可跨行、可含反斜杠与注释）
  * itertools.batched —— 标准库新增的批量切分工具
  * typing.override —— 显式声明方法覆盖
"""

from __future__ import annotations

import itertools
import sys
from typing import override

print(f"当前解释器: Python {sys.version.split()[0]}")

# ---------------------------------------------------------------------------
# 1) PEP 701：f-string 内部可以复用同种引号、跨行书写，表达式里还能用反斜杠
#    下面 banner 里外都是双引号，table 的表达式里有 "\n" —— 3.11 及以前都是语法错误
# ---------------------------------------------------------------------------
user = {"name": "Ada", "lang": "Python 3.12"}
banner = f"Hello {user["name"]}, 你是 {user["lang"]} 用户！"
print("1) PEP 701 同引号嵌套:", banner)

table = f"""用户信息：
{
    "\n".join(
        f"  - {k}: {v!r}"
        for k, v in user.items()
    )
}"""
print("   f-string 表达式可以跨行书写：")
print(table)

# ---------------------------------------------------------------------------
# 2) PEP 695：type 类型别名语句（惰性求值，可携带泛型参数）
# ---------------------------------------------------------------------------
type Matrix = list[list[float]]
type Pair[T] = tuple[T, T]


def add_matrices(a: Matrix, b: Matrix) -> Matrix:
    return [[x + y for x, y in zip(row_a, row_b)] for row_a, row_b in zip(a, b)]


m = add_matrices([[1.0, 2.0], [3.0, 4.0]], [[10.0, 20.0], [30.0, 40.0]])
print("2) type 别名 Matrix ->", m, "| Pair[str] ->", Pair[str])


# ---------------------------------------------------------------------------
# 3) PEP 695：函数与类的泛型参数（不再需要 TypeVar / Generic）
# ---------------------------------------------------------------------------
def chunk[T](items: list[T], size: int) -> list[list[T]]:
    """把列表按 size 切块。T 会被自动推断，不需要 TypeVar。"""
    return [items[i : i + size] for i in range(0, len(items), size)]


class Stack[T]:
    """一个类型安全的栈，T 直接写在类名后面。"""

    def __init__(self) -> None:
        self._items: list[T] = []

    def push(self, item: T) -> None:
        self._items.append(item)

    def pop(self) -> T:
        return self._items.pop()

    def __len__(self) -> int:
        return len(self._items)


print("3) 泛型函数 chunk:", chunk([1, 2, 3, 4, 5, 6, 7], 3))
stack: Stack[str] = Stack()
for word in ("a", "b", "c"):
    stack.push(word)
print("   泛型类 Stack[str]:", [stack.pop() for _ in range(len(stack))])

# 运行期的类型参数信息也是可用的（PEP 695）
print("   运行期可见的泛型参数:", chunk.__type_params__, Stack.__type_params__)


# ---------------------------------------------------------------------------
# 4) itertools.batched：按固定长度分批（最后一批可能不足）
# ---------------------------------------------------------------------------
stream = [11, 12, 13, 14, 15]
print("4) itertools.batched(2):", list(itertools.batched(stream, 2)))
print("   不足一整批的尾巴单独成组:", list(itertools.batched("ABCDEFG", 3)))
# 备注：batched(..., strict=True) 是 Python 3.13 才加入的参数，3.12 里只有 (iterable, n)

# ---------------------------------------------------------------------------
# 5) typing.override：显式标记「我覆盖了父类方法」，拼错方法名时可被类型检查器发现
# ---------------------------------------------------------------------------
class Base:
    def greet(self) -> str:
        return "base"


class Child(Base):
    @override
    def greet(self) -> str:
        return "child → " + super().greet()


print("5) typing.override:", Child().greet())

print("\n全部 3.12 新特性演示通过 ✅")
