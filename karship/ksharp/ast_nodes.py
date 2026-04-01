from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class Node:
    pass


class Stmt(Node):
    pass


class Expr(Node):
    pass


@dataclass(slots=True)
class Program(Node):
    statements: list[Stmt]


@dataclass(slots=True)
class VarDecl(Stmt):
    name: str
    initializer: Expr
    is_const: bool = False


@dataclass(slots=True)
class FunctionDecl(Stmt):
    name: str
    params: list[str]
    body: list[Stmt]


@dataclass(slots=True)
class IfStmt(Stmt):
    condition: Expr
    then_branch: list[Stmt]
    elif_branches: list[tuple[Expr, list[Stmt]]]
    else_branch: list[Stmt] | None


@dataclass(slots=True)
class WhileStmt(Stmt):
    condition: Expr
    body: list[Stmt]


@dataclass(slots=True)
class EachStmt(Stmt):
    iterator_name: str
    iterable: Expr
    body: list[Stmt]


@dataclass(slots=True)
class ReturnStmt(Stmt):
    value: Expr | None


@dataclass(slots=True)
class BreakStmt(Stmt):
    pass


@dataclass(slots=True)
class ContinueStmt(Stmt):
    pass


@dataclass(slots=True)
class SparkStmt(Stmt):
    args: list[Expr]


@dataclass(slots=True)
class UseStmt(Stmt):
    module_path: str


@dataclass(slots=True)
class ExprStmt(Stmt):
    expr: Expr


@dataclass(slots=True)
class Literal(Expr):
    value: Any


@dataclass(slots=True)
class Variable(Expr):
    name: str


@dataclass(slots=True)
class Assign(Expr):
    name: str
    value: Expr


@dataclass(slots=True)
class Grouping(Expr):
    expr: Expr


@dataclass(slots=True)
class Unary(Expr):
    operator: str
    right: Expr


@dataclass(slots=True)
class Binary(Expr):
    left: Expr
    operator: str
    right: Expr


@dataclass(slots=True)
class Logical(Expr):
    left: Expr
    operator: str
    right: Expr


@dataclass(slots=True)
class Call(Expr):
    callee: Expr
    args: list[Expr]


@dataclass(slots=True)
class GetExpr(Expr):
    target: Expr
    name: str


@dataclass(slots=True)
class IndexExpr(Expr):
    target: Expr
    index: Expr


@dataclass(slots=True)
class ListLiteral(Expr):
    elements: list[Expr]
