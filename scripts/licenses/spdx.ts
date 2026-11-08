// Minimal SPDX license-expression evaluator.
// Grammar: expr := term ("OR" term)*; term := factor ("AND" factor)*;
//          factor := "(" expr ")" | id
// "WITH" exceptions and anything unparsable are rejected so that a human
// reviews them and records an override.

type Token = "(" | ")" | "AND" | "OR" | { id: string };

function tokenize(expression: string): Token[] | null {
  const tokens: Token[] = [];
  for (const raw of expression
    .replaceAll("(", " ( ")
    .replaceAll(")", " ) ")
    .split(/\s+/)) {
    if (raw === "") continue;
    if (raw === "(" || raw === ")" || raw === "AND" || raw === "OR") {
      tokens.push(raw);
    } else if (raw === "WITH" || !/^[A-Za-z0-9.+-]+$/.test(raw)) {
      return null;
    } else {
      tokens.push({ id: raw });
    }
  }
  return tokens;
}

class Parser {
  private position = 0;

  constructor(
    private readonly tokens: readonly Token[],
    private readonly allowed: ReadonlySet<string>,
  ) {}

  parse(): boolean | null {
    const value = this.expr();
    if (value === null || this.position !== this.tokens.length) return null;
    return value;
  }

  private expr(): boolean | null {
    let value = this.term();
    while (value !== null && this.tokens[this.position] === "OR") {
      this.position += 1;
      const right = this.term();
      value = right === null ? null : value || right;
    }
    return value;
  }

  private term(): boolean | null {
    let value = this.factor();
    while (value !== null && this.tokens[this.position] === "AND") {
      this.position += 1;
      const right = this.factor();
      value = right === null ? null : value && right;
    }
    return value;
  }

  private factor(): boolean | null {
    const token = this.tokens[this.position];
    if (token === undefined) return null;
    this.position += 1;
    if (token === "(") {
      const value = this.expr();
      if (this.tokens[this.position] !== ")") return null;
      this.position += 1;
      return value;
    }
    if (typeof token === "object") return this.allowed.has(token.id);
    return null;
  }
}

/** True when the expression is valid SPDX and is satisfiable with allowed ids only. */
export function isAllowedExpression(
  expression: string,
  allowed: ReadonlySet<string>,
): boolean {
  const tokens = tokenize(expression);
  if (tokens === null || tokens.length === 0) return false;
  return new Parser(tokens, allowed).parse() === true;
}
