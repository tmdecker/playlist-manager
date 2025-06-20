from rate_limiter import rate_limited_call


def sort_playlist_by_release_date(sp, playlist_id, reverse=True):
    """
    Sort a Spotify playlist by release date without removing/re-adding tracks.

    Args:
        sp: Spotipy client instance
        playlist_id: Spotify playlist ID
        reverse: If True, newest songs first. If False, oldest songs first.

    Returns:
        Number of reorder operations performed
    """

    # Get all tracks from the playlist with rate limiting
    tracks = []
    results = rate_limited_call(sp.playlist_items, playlist_id, limit=100)
    tracks.extend(results["items"])

    # Handle playlists with more than 100 tracks
    while results["next"]:
        results = rate_limited_call(sp.next, results)
        tracks.extend(results["items"])

    # Extract track info with release dates and current positions
    track_data = []
    for i, item in enumerate(tracks):
        if item["track"] and item["track"]["album"]:
            track = item["track"]
            album = track["album"]

            # Get release date (use release_date_precision to handle partial dates)
            release_date = album["release_date"]
            precision = album.get("release_date_precision", "day")

            # Normalize dates to handle different precisions
            if precision == "year":
                release_date += "-01-01"
            elif precision == "month":
                release_date += "-01"

            track_data.append(
                {
                    "position": i,
                    "release_date": release_date,
                    "name": track["name"],
                    "artist": track["artists"][0]["name"] if track["artists"] else "Unknown",
                    "uri": track["uri"],
                }
            )

    # Sort by release date
    sorted_tracks = sorted(track_data, key=lambda x: x["release_date"], reverse=reverse)

    # Calculate the new order
    new_positions = {track["position"]: i for i, track in enumerate(sorted_tracks)}

    # Optimize reordering to minimize API calls
    reorder_count = 0
    processed = set()

    for current_pos in range(len(track_data)):
        if current_pos in processed:
            continue

        # Find where this track should go
        target_pos = new_positions[current_pos]

        if current_pos != target_pos:
            # Use playlist_reorder_items to move the track
            try:
                rate_limited_call(
                    sp.playlist_reorder_items,
                    playlist_id,
                    range_start=current_pos,
                    insert_before=target_pos,
                    range_length=1,
                )
                reorder_count += 1

                # Update our tracking after the move
                # When moving forward, positions shift
                if target_pos > current_pos:
                    for i in range(current_pos + 1, target_pos + 1):
                        for pos, new_pos in new_positions.items():
                            if new_pos == i:
                                new_positions[pos] = i - 1
                    new_positions[current_pos] = target_pos
                else:
                    # When moving backward, positions shift differently
                    for i in range(target_pos, current_pos):
                        for pos, new_pos in new_positions.items():
                            if new_pos == i:
                                new_positions[pos] = i + 1
                    new_positions[current_pos] = target_pos

                processed.add(current_pos)

            except Exception as e:
                print(f"Error reordering track at position {current_pos}: {e}")

    return reorder_count


def batch_sort_playlist(sp, playlist_id, reverse=True):
    """
    Alternative approach using a more efficient batch reordering strategy.
    This minimizes the number of API calls by calculating the final positions
    and moving tracks in an optimized order.
    """

    # Get all tracks with rate limiting
    tracks = []
    results = rate_limited_call(sp.playlist_items, playlist_id, limit=100)
    tracks.extend(results["items"])

    while results["next"]:
        results = rate_limited_call(sp.next, results)
        tracks.extend(results["items"])

    # Create track data with release dates
    track_data = []
    for i, item in enumerate(tracks):
        if item["track"] and item["track"]["album"]:
            track = item["track"]
            album = track["album"]
            release_date = album["release_date"]

            # Handle different date precisions
            if len(release_date) == 4:  # Year only
                release_date += "-01-01"
            elif len(release_date) == 7:  # Year-month
                release_date += "-01"

            track_data.append({"index": i, "release_date": release_date, "track": track})

    # Sort by release date
    sorted_indices = sorted(
        range(len(track_data)), key=lambda i: track_data[i]["release_date"], reverse=reverse
    )

    # Build a sequence of moves to sort the playlist
    moves = []
    current_positions = list(range(len(track_data)))

    for target_pos, source_idx in enumerate(sorted_indices):
        current_pos = current_positions.index(source_idx)
        if current_pos != target_pos:
            moves.append((current_pos, target_pos))
            # Update the position tracking
            item = current_positions.pop(current_pos)
            current_positions.insert(target_pos, item)

    # Execute the moves
    for current_pos, target_pos in moves:
        try:
            rate_limited_call(
                sp.playlist_reorder_items,
                playlist_id,
                range_start=current_pos,
                insert_before=target_pos + 1 if target_pos > current_pos else target_pos,
                range_length=1,
            )
        except Exception as e:
            print(f"Error moving track from {current_pos} to {target_pos}: {e}")

    return len(moves)


