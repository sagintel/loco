import sys
from loco.agent import load_skills, detect_skills

skills = load_skills()
print(f'Total skills loaded: {len(skills)}')
print('---')
for s in skills:
    print(f'  {s.get("id", "none")}: {s.get("title", "none")[:50]}')
print('---')

queries = [
    ('review my code for bugs and security issues', 'code_review'),
    ('write unit tests with edge cases', 'unit_test'),
    ('optimize this slow function bottleneck', 'optimize'),
    ('build me a react landing page with css', 'frontend-design'),
]

for query, expected_id in queries:
    matched = detect_skills(query)
    matched_id = matched['id'] if matched else "NONE"
    print(f"Query: '{query}'")
    print(f"  Matched: {matched_id} (Expected: {expected_id})")
    assert matched_id == expected_id or (matched and matched_id in expected_id), f"Failed: {query}"

print("All assertions passed!")
