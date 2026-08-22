from pipeline.adapters.pa_monroe_bid4assets import MonroeBid4AssetsAdapter


def test_parses_embedded_bid4assets_grid_data() -> None:
    html = '''
    <script>kendo.syncReady(function(){jQuery("#Auctions_grid").kendoGrid({
      "data":{"Data":[{"AuctionID":1278681,"Address":"2170 SANCTUARY DRIVE"}],"Total":1}
    });});</script>
    '''
    assert MonroeBid4AssetsAdapter._grid_rows(html) == [
        {"AuctionID": 1278681, "Address": "2170 SANCTUARY DRIVE"}
    ]


def test_parses_full_detail_address() -> None:
    html = '''
    <div class="item-specifics-table"><table><tr>
      <td><strong>Address</strong></td>
      <td>2170 SANCTUARY DRIVE<br>EAST STROUDSBURG, PA 18302</td>
    </tr></table></div>
    '''
    assert MonroeBid4AssetsAdapter._detail_address(html) == (
        "2170 SANCTUARY DRIVE EAST STROUDSBURG, PA 18302"
    )
