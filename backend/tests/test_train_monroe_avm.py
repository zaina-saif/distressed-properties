from pandas import DataFrame

from pipeline.train_monroe_avm import chronological_split


def test_monroe_chronological_split_keeps_future_rows_out_of_training() -> None:
    frame = DataFrame({"sale_year": [2017, 2020, 2021, 2022], "sale_price": [1, 2, 3, 4]})
    training, validation, test = chronological_split(frame)
    assert training.sale_year.tolist() == [2017, 2020]
    assert validation.sale_year.tolist() == [2021]
    assert test.sale_year.tolist() == [2022]
