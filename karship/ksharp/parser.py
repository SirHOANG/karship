from __future__ import annotations

from .ast_nodes import (
    Assign,
    Binary,
    BreakStmt,
    Call,
    ContinueStmt,
    EachStmt,
    Expr,
    ExprStmt,
    FunctionDecl,
    GetExpr,
    Grouping,
    IfStmt,
    IndexExpr,
    ListLiteral,
    Literal,
    Logical,
    Program,
    ReturnStmt,
    SparkStmt,
    Stmt,
    Unary,
    UseStmt,
    VarDecl,
    Variable,
    WhileStmt,
)
from .tokens import Token


class KSharpParserError(Exception):
    pass


SEPARATOR_TYPES = {"NEWLINE", "SEMICOLON"}


class Parser:
    def __init__(self, tokens: list[Token], filename: str = "<memory>") -> None:
        self.tokens = tokens
        self.filename = filename
        self._current = 0

    def parse(self) -> Program:
        statements: list[Stmt] = []
        while not self._is_at_end():
            self._skip_separators()
            if self._is_at_end():
                break
            statements.append(self._declaration())
        return Program(statements)

    def _declaration(self) -> Stmt:
        if self._match_keyword("let"):
            return self._variable_declaration(is_const=False)
        if self._match_keyword("lock"):
            return self._variable_declaration(is_const=True)
        if self._match_keyword("forge"):
            return self._function_declaration()
        return self._statement()

    def _statement(self) -> Stmt:
        if self._match_keyword("if"):
            return self._if_statement()
        if self._match_keyword("while"):
            return self._while_statement()
        if self._match_keyword("each"):
            return self._each_statement()
        if self._match_keyword("return"):
            return self._return_statement()
        if self._match_keyword("break"):
            return BreakStmt()
        if self._match_keyword("continue"):
            return ContinueStmt()
        if self._match_keyword("spark"):
            return self._spark_statement()
        if self._match_keyword("use"):
            return self._use_statement()
        return self._expression_statement()

    def _variable_declaration(self, is_const: bool) -> VarDecl:
        name = self._consume("IDENTIFIER", "Expected variable name.")
        self._consume("EQUAL", "Expected '=' after variable name.")
        initializer = self._expression()
        return VarDecl(name=name.lexeme, initializer=initializer, is_const=is_const)

    def _function_declaration(self) -> FunctionDecl:
        name = self._consume("IDENTIFIER", "Expected function name after 'forge'.")
        self._consume("LEFT_PAREN", "Expected '(' after function name.")
        params: list[str] = []
        if not self._check("RIGHT_PAREN"):
            while True:
                param = self._consume("IDENTIFIER", "Expected parameter name.")
                params.append(param.lexeme)
                if not self._match("COMMA"):
                    break
        self._consume("RIGHT_PAREN", "Expected ')' after parameters.")
        body = self._block()
        return FunctionDecl(name=name.lexeme, params=params, body=body)

    def _if_statement(self) -> IfStmt:
        condition = self._expression()
        then_branch = self._block()
        elif_branches: list[tuple[Expr, list[Stmt]]] = []
        while self._match_keyword("elif"):
            branch_condition = self._expression()
            branch_body = self._block()
            elif_branches.append((branch_condition, branch_body))
        else_branch = self._block() if self._match_keyword("else") else None
        return IfStmt(
            condition=condition,
            then_branch=then_branch,
            elif_branches=elif_branches,
            else_branch=else_branch,
        )

    def _while_statement(self) -> WhileStmt:
        condition = self._expression()
        body = self._block()
        return WhileStmt(condition=condition, body=body)

    def _each_statement(self) -> EachStmt:
        iterator = self._consume("IDENTIFIER", "Expected iterator name after 'each'.")
        self._consume_keyword("in", "Expected 'in' in each-loop.")
        iterable = self._expression()
        body = self._block()
        return EachStmt(iterator_name=iterator.lexeme, iterable=iterable, body=body)

    def _return_statement(self) -> ReturnStmt:
        if self._check("RIGHT_BRACE") or self._check_separator() or self._is_at_end():
            return ReturnStmt(value=None)
        return ReturnStmt(value=self._expression())

    def _spark_statement(self) -> SparkStmt:
        args: list[Expr] = []
        if self._match("LEFT_PAREN"):
            if not self._check("RIGHT_PAREN"):
                while True:
                    args.append(self._expression())
                    if not self._match("COMMA"):
                        break
            self._consume("RIGHT_PAREN", "Expected ')' after spark arguments.")
            return SparkStmt(args=args)
        args.append(self._expression())
        while self._match("COMMA"):
            args.append(self._expression())
        return SparkStmt(args=args)

    def _use_statement(self) -> UseStmt:
        if self._match("LEFT_PAREN"):
            module = self._consume("STRING", "Expected module path string in use(...).")
            self._consume("RIGHT_PAREN", "Expected ')' after use module path.")
            return UseStmt(module_path=module.literal)
        module = self._consume("STRING", "Expected module path string after 'use'.")
        return UseStmt(module_path=module.literal)

    def _expression_statement(self) -> ExprStmt:
        return ExprStmt(expr=self._expression())

    def _block(self) -> list[Stmt]:
        self._consume("LEFT_BRACE", "Expected '{' to start block.")
        statements: list[Stmt] = []
        while not self._check("RIGHT_BRACE") and not self._is_at_end():
            self._skip_separators()
            if self._check("RIGHT_BRACE"):
                break
            statements.append(self._declaration())
        self._consume("RIGHT_BRACE", "Expected '}' to close block.")
        return statements

    def _expression(self) -> Expr:
        return self._assignment()

    def _assignment(self) -> Expr:
        expr = self._or()
        if self._match("EQUAL"):
            equals = self._previous()
            value = self._assignment()
            if isinstance(expr, Variable):
                return Assign(name=expr.name, value=value)
            raise self._error(equals, "Invalid assignment target.")
        return expr

    def _or(self) -> Expr:
        expr = self._and()
        while self._match_keyword("or"):
            operator = self._previous().lexeme
            right = self._and()
            expr = Logical(left=expr, operator=operator, right=right)
        return expr

    def _and(self) -> Expr:
        expr = self._equality()
        while self._match_keyword("and"):
            operator = self._previous().lexeme
            right = self._equality()
            expr = Logical(left=expr, operator=operator, right=right)
        return expr

    def _equality(self) -> Expr:
        expr = self._comparison()
        while self._match("BANG_EQUAL", "EQUAL_EQUAL"):
            operator = self._previous().lexeme
            right = self._comparison()
            expr = Binary(left=expr, operator=operator, right=right)
        return expr

    def _comparison(self) -> Expr:
        expr = self._term()
        while self._match("GREATER", "GREATER_EQUAL", "LESS", "LESS_EQUAL"):
            operator = self._previous().lexeme
            right = self._term()
            expr = Binary(left=expr, operator=operator, right=right)
        return expr

    def _term(self) -> Expr:
        expr = self._factor()
        while self._match("PLUS", "MINUS"):
            operator = self._previous().lexeme
            right = self._factor()
            expr = Binary(left=expr, operator=operator, right=right)
        return expr

    def _factor(self) -> Expr:
        expr = self._unary()
        while self._match("STAR", "SLASH", "PERCENT"):
            operator = self._previous().lexeme
            right = self._unary()
            expr = Binary(left=expr, operator=operator, right=right)
        return expr

    def _unary(self) -> Expr:
        if self._match("BANG", "MINUS"):
            operator = self._previous().lexeme
            right = self._unary()
            return Unary(operator=operator, right=right)
        if self._match_keyword("not"):
            operator = self._previous().lexeme
            right = self._unary()
            return Unary(operator=operator, right=right)
        return self._call()

    def _call(self) -> Expr:
        expr = self._primary()
        while True:
            if self._match("LEFT_PAREN"):
                args: list[Expr] = []
                if not self._check("RIGHT_PAREN"):
                    while True:
                        args.append(self._expression())
                        if not self._match("COMMA"):
                            break
                self._consume("RIGHT_PAREN", "Expected ')' after arguments.")
                expr = Call(callee=expr, args=args)
            elif self._match("DOT"):
                name = self._consume("IDENTIFIER", "Expected property name after '.'.")
                expr = GetExpr(target=expr, name=name.lexeme)
            elif self._match("LEFT_BRACKET"):
                index = self._expression()
                self._consume("RIGHT_BRACKET", "Expected ']' after index.")
                expr = IndexExpr(target=expr, index=index)
            else:
                break
        return expr

    def _primary(self) -> Expr:
        if self._match("NUMBER"):
            return Literal(self._previous().literal)
        if self._match("STRING"):
            return Literal(self._previous().literal)
        if self._match_keyword("true"):
            return Literal(True)
        if self._match_keyword("false"):
            return Literal(False)
        if self._match_keyword("nil"):
            return Literal(None)
        if self._match("IDENTIFIER"):
            return Variable(self._previous().lexeme)
        if self._match("LEFT_PAREN"):
            expr = self._expression()
            self._consume("RIGHT_PAREN", "Expected ')' after expression.")
            return Grouping(expr=expr)
        if self._match("LEFT_BRACKET"):
            elements: list[Expr] = []
            if not self._check("RIGHT_BRACKET"):
                while True:
                    elements.append(self._expression())
                    if not self._match("COMMA"):
                        break
            self._consume("RIGHT_BRACKET", "Expected ']' after list literal.")
            return ListLiteral(elements=elements)
        raise self._error(self._peek(), "Expected expression.")

    def _skip_separators(self) -> None:
        while self._match(*SEPARATOR_TYPES):
            pass

    def _check_separator(self) -> bool:
        return self._peek().type in SEPARATOR_TYPES

    def _consume_keyword(self, keyword: str, message: str) -> Token:
        if self._check_keyword(keyword):
            return self._advance()
        raise self._error(self._peek(), message)

    def _match_keyword(self, keyword: str) -> bool:
        if self._check_keyword(keyword):
            self._advance()
            return True
        return False

    def _check_keyword(self, keyword: str) -> bool:
        if self._is_at_end():
            return False
        token = self._peek()
        return token.type == "KEYWORD" and token.lexeme == keyword

    def _match(self, *types: str) -> bool:
        for token_type in types:
            if self._check(token_type):
                self._advance()
                return True
        return False

    def _consume(self, token_type: str, message: str) -> Token:
        if self._check(token_type):
            return self._advance()
        raise self._error(self._peek(), message)

    def _check(self, token_type: str) -> bool:
        if self._is_at_end():
            return False
        return self._peek().type == token_type

    def _advance(self) -> Token:
        if not self._is_at_end():
            self._current += 1
        return self._previous()

    def _is_at_end(self) -> bool:
        return self._peek().type == "EOF"

    def _peek(self) -> Token:
        return self.tokens[self._current]

    def _previous(self) -> Token:
        return self.tokens[self._current - 1]

    def _error(self, token: Token, message: str) -> KSharpParserError:
        where = token.location()
        return KSharpParserError(
            f"{self.filename}:{where} ParserError: {message} Found '{token.lexeme}'."
        )
