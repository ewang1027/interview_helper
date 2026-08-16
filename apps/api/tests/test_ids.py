from api.ids import new_id


def test_ids_are_unique_and_lexically_sortable_by_creation_time():
    """docs/API.md: IDs are ULIDs — sortable by creation time."""
    ids = [new_id() for _ in range(50)]
    assert len(set(ids)) == 50
    assert ids == sorted(ids)
    assert all(len(i) == 26 for i in ids)
