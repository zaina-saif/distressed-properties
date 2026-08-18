from pipeline.match_properties_to_modiv import similarity, street_key

def test_street_key_normalizes_common_suffixes():
    assert street_key("11 Manor Drive") == street_key("11 MANOR DR")

def test_similarity_requires_exact_street_number():
    assert similarity("11 Manor Drive","11 MANOR DR")==1
    assert similarity("11 Manor Drive","12 MANOR DR")==0
