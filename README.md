"Now Playing" HTML / CSS Widget for Rekordbox
---------------------------------------------

![Now Playing](/assets/example_widget.png "Now Playing")

### What is it?

The widget shows the latest loaded song by Rekordbox in a fully
customizable webpage.

#### Use cases

* Overlay the widget in OBS using Browser Source. 

#### Features

* HTML and CSS. Easy to modify. Style and apply effects however you like.
* Supports Rekordbox database 6 / 7.
* Polls Rekordbox on an interval. 


### Get started

#### Installation

1. Download this repository.
2. Use `uv` (recommended!). Installation instructions [here](https://docs.astral.sh/uv/getting-started/installation/).
3. Resolve dependencies. Run: `uv sync`

#### Running

1. Run the Websocket server: `uv run poller.py`. You should see:
    ```shell
    [20:07:32] pyrekordbox.db6.database:WARNING  - Rekordbox is running!
    2026-02-07 20:07:32,567 - WARNING - Rekordbox is running!
    2026-02-07 20:07:32,612 - INFO - server listening on 127.0.0.1:8080
    ```
2. Open [assets/widget.html](./assets/widget.html) in a web browser window.

#### What should happen?

The webpage will automatically connect to the Websocket server. The track info
should display once Rekordbox writes it to the database.

### Rekordbox

If you want to change the time it takes for Rekordbox to update with the latest song info,
change the **"Playback time setting"**  in Rekordbox.  For more information,
search the [Rekordbox manual](https://rekordbox.com/en/download/#manual).

### Feature requests

This project is open to feature requests.
