from app.dedupe import merge_concepts


def test_same_concept_from_several_pages_becomes_one():
    items = [
        {"term": "교착 상태 (Deadlock)", "definition": "프로세스들이 서로 자원을 기다리며 멈춘 상황.", "page_no": 1},
        {"term": "교착 상태", "definition": "두 개 이상의 프로세스가 서로가 가진 자원을 기다리며 영원히 진행되지 못하는 상태. 예) 식사하는 철학자", "page_no": 2},
        {"term": "상호 배제", "definition": "한 번에 하나만 쓴다.", "page_no": 2},
        {"term": "교착 예방", "definition": "조건 하나를 깬다.", "page_no": 4},
        {"term": "교착 상태 예방", "definition": "네 조건 중 하나를 깨뜨려 교착을 막는다. 예) 자원 번호 순서", "page_no": 4},
    ]
    merged = merge_concepts(items)
    assert [m["term"] for m in merged] == ["교착 상태 (Deadlock)", "상호 배제", "교착 예방"]
    assert merged[0]["pages"] == [1, 2] and "철학자" in merged[0]["definition"]
    assert "번호 순서" in merged[2]["definition"]
