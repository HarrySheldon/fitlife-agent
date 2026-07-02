from backend.rag.retriever import retrieve_knowledge


def test_retriever_returns_source_metadata_for_protein_query():
    results = retrieve_knowledge("蛋白质 每公斤体重 摄入 建议", top_k=2)

    assert results
    assert results[0]["source"].endswith(".md")
    assert results[0]["heading"]
    assert "蛋白质" in results[0]["text"]


def test_retriever_finds_meal_replacement_guidance():
    results = retrieve_knowledge("不想吃鸡胸肉 替代 食物", top_k=3)

    assert any("meal_templates.md" == item["source"] for item in results)
