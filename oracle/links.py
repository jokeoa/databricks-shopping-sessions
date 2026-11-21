from collections import defaultdict
from leaf import lines


def names(paths):
    # Graph traversal makes the oracle independent of union-find order and roots.
    graph = defaultdict(set)
    for path in paths:
        for _, _, pair in lines(path, 2):
            if pair and all(pair):
                a, b = pair
                graph[a].add(b)
                graph[b].add(a)
    result = {}
    for start in graph:
        if start in result:
            continue
        component = {start}
        todo = [start]
        while todo:
            for key in graph[todo.pop()]:
                if key not in component:
                    component.add(key)
                    todo.append(key)
        name = min(component)
        result.update(dict.fromkeys(component, name))
    return result
