import ast
import os

TARGET_DECORATOR = "with_postgres_session"


class SessionChecker(ast.NodeVisitor):
    def __init__(self, filename):
        self.filename = filename
        self.decorated_methods = (
            set()
        )  # Set of method names that use the decorator
        self.missing_session_calls = []  # [(line number, method name)]

    def visit_FunctionDef(self, node):
        for deco in node.decorator_list:
            if isinstance(deco, ast.Name) and deco.id == TARGET_DECORATOR:
                self.decorated_methods.add(node.name)
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node):
        self.visit_FunctionDef(node)

    def visit_Await(self, node):
        if isinstance(node.value, ast.Call):
            call = node.value
            func = call.func

            # Get function name
            if isinstance(func, ast.Attribute):
                method_name = func.attr
                if method_name in self.decorated_methods:
                    # Check if postgres_session is passed
                    has_session = any(
                        isinstance(arg, ast.keyword)
                        and arg.arg == "postgres_session"
                        for arg in call.keywords
                    )
                    if not has_session:
                        self.missing_session_calls.append(
                            (node.lineno, method_name)
                        )
        self.generic_visit(node)


def scan_file(filepath):
    with open(filepath, "r", encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename=filepath)
    checker = SessionChecker(filepath)
    checker.visit(tree)
    return checker.decorated_methods, checker.missing_session_calls


def scan_directory(directory):
    results = []
    for root, _, files in os.walk(directory):
        for file in files:
            if file.endswith(".py"):
                filepath = os.path.join(root, file)
                try:
                    _, missing = scan_file(filepath)
                    if missing:
                        results.append((filepath, missing))
                except Exception as e:
                    print(f"Failed to scan {filepath}: {e}")
    return results


if __name__ == "__main__":
    import sys

    path = sys.argv[1] if len(sys.argv) > 1 else "."

    print(f"Scanning Python files in {path}...\n")
    issues = scan_directory(path)

    for filepath, calls in issues:
        print(f"\nFile: {filepath}")
        for lineno, method in calls:
            print(
                f"  Line {lineno}: Missing `postgres_session` in call to `{method}()`"
            )
