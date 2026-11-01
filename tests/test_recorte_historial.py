from dzlabs.graph.state import recortar_historial


def test_recorte_empieza_en_user_texto():
    msgs = []
    for i in range(30):
        msgs.append({"role": "user", "content": f"u{i}"})
        msgs.append(
            {
                "role": "assistant",
                "content": [{"type": "tool_use", "id": "t", "name": "x", "input": {}}],
            }
        )
        msgs.append(
            {
                "role": "user",
                "content": [{"type": "tool_result", "tool_use_id": "t", "content": "r"}],
            }
        )
        msgs.append({"role": "assistant", "content": [{"type": "text", "text": "a"}]})
    out = recortar_historial(msgs, max_n=10)
    assert out[0]["role"] == "user" and isinstance(out[0]["content"], str)
    assert len(out) <= 10
    assert recortar_historial(msgs[:5], max_n=10) == msgs[:5]
