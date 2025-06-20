import logging
from collections import defaultdict
from rate_limiter import rate_limited_call


def simulate_remove_positions(playlist_simulation, positions_to_remove):
    """
    Remove tracks at specified positions from playlist simulation.
    Returns new playlist simulation with tracks removed.
    
    Args:
        playlist_simulation: List of URIs representing playlist
        positions_to_remove: List of positions to remove (will be sorted)
    
    Returns:
        New playlist simulation with specified positions removed
    """
    # Sort positions in descending order to avoid index shifting issues
    sorted_positions = sorted(positions_to_remove, reverse=True)
    new_playlist = playlist_simulation.copy()
    
    for pos in sorted_positions:
        if 0 <= pos < len(new_playlist):
            new_playlist.pop(pos)
    
    return new_playlist


def simulate_add_at_position(playlist_simulation, uri, position):
    """
    Add a track URI at specified position in playlist simulation.
    
    Args:
        playlist_simulation: List of URIs representing playlist
        uri: Track URI to add
        position: Position to insert at (0-indexed)
    
    Returns:
        New playlist simulation with track added
    """
    new_playlist = playlist_simulation.copy()
    # Ensure position is within bounds
    position = max(0, min(position, len(new_playlist)))
    new_playlist.insert(position, uri)
    return new_playlist


def find_current_positions(playlist_simulation, target_uri):
    """
    Find all current positions of a specific URI in playlist simulation.
    
    Args:
        playlist_simulation: List of URIs representing playlist
        target_uri: URI to search for
    
    Returns:
        List of positions where the URI is found
    """
    positions = []
    for i, uri in enumerate(playlist_simulation):
        if uri == target_uri:
            positions.append(i)
    return positions


def remove_duplicates_from_playlist(sp, playlist_id, dry_run=False, debug=True):
    """
    Remove duplicate tracks from a Spotify playlist.
    Keeps the first occurrence (topmost position) and removes subsequent duplicates.
    
    Args:
        sp: Spotipy client instance
        playlist_id: Spotify playlist ID
        dry_run: If True, analyze duplicates but don't actually remove them
        debug: If True, enable detailed logging
    
    Returns:
        Dictionary with removal statistics and debug information
    """
    # Setup logging
    logger = logging.getLogger(__name__)
    if debug:
        logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    
    # Step 1: Get playlist info and initial snapshot
    if debug:
        logger.info(f"Starting duplicate removal for playlist {playlist_id} (dry_run={dry_run})")
    
    playlist_info = rate_limited_call(sp.playlist, playlist_id, fields="snapshot_id,name,tracks.total")
    initial_snapshot = playlist_info["snapshot_id"]
    playlist_name = playlist_info["name"]
    total_tracks_count = playlist_info["tracks"]["total"]
    
    if debug:
        logger.info(f"Playlist: '{playlist_name}' ({total_tracks_count} tracks, snapshot: {initial_snapshot})")
    
    # Step 2: Get the track list of the playlist with rate limiting
    tracks = []
    results = rate_limited_call(sp.playlist_items, playlist_id, limit=100)
    tracks.extend(results["items"])

    # Handle playlists with more than 100 tracks
    while results["next"]:
        results = rate_limited_call(sp.next, results)
        tracks.extend(results["items"])
    
    if debug:
        logger.info(f"Fetched {len(tracks)} tracks from playlist")

    # Step 3: Identify duplicate tracks by title and artists, save them as dict including position
    track_positions = {}  # track_key -> list of positions
    duplicate_positions_to_remove = []  # positions to remove, sorted bottom to top
    uri_usage = defaultdict(list)  # Track URI usage for debugging identical URIs

    for position, item in enumerate(tracks):
        if item["track"] and item["track"]["name"]:
            track_name = item["track"]["name"].lower().strip()
            # Get all artists and sort them for consistent comparison
            artists = []
            if item["track"]["artists"]:
                artists = sorted([artist["name"].lower().strip() for artist in item["track"]["artists"]])

            # Create a unique key based on track name and all artists
            track_key = f"{track_name}|||{'|||'.join(artists)}"

            if track_key not in track_positions:
                track_positions[track_key] = []

            track_info = {
                "position": position,
                "uri": item["track"]["uri"],
                "name": item["track"]["name"],
                "artist": item["track"]["artists"][0]["name"] if item["track"]["artists"] else "Unknown",
                "all_artists": [artist["name"] for artist in item["track"]["artists"]] if item["track"]["artists"] else [],
                "album": item["track"]["album"]["name"] if item["track"]["album"] else "Unknown"
            }
            
            track_positions[track_key].append(track_info)
            
            # Track URI usage for debugging
            uri_usage[item["track"]["uri"]].append({
                "position": position,
                "track_key": track_key,
                "name": item["track"]["name"],
                "artist": item["track"]["artists"][0]["name"] if item["track"]["artists"] else "Unknown"
            })

    # Debug: Log URI usage patterns
    if debug:
        identical_uri_cases = {uri: info for uri, info in uri_usage.items() if len(info) > 1}
        if identical_uri_cases:
            logger.warning(f"Found {len(identical_uri_cases)} URIs with multiple occurrences:")
            for uri, occurrences in identical_uri_cases.items():
                logger.warning(f"  URI {uri}: {len(occurrences)} occurrences")
                for occ in occurrences:
                    logger.warning(f"    Position {occ['position']}: {occ['name']} - {occ['artist']}")
    
    # Find duplicates and mark positions for removal
    duplicate_groups = []
    for track_key, positions in track_positions.items():
        if len(positions) > 1:
            # This track has duplicates
            # Sort positions by their position number to keep the first occurrence
            positions.sort(key=lambda x: x["position"])

            # Check for identical URIs within this duplicate group
            uris_in_group = [pos["uri"] for pos in positions]
            has_identical_uris = len(set(uris_in_group)) < len(uris_in_group)
            
            duplicate_group = {
                "track_name": positions[0]["name"],
                "artist": positions[0]["artist"],
                "all_artists": positions[0]["all_artists"],
                "count": len(positions),
                "positions": [pos["position"] for pos in positions],
                "albums": [pos["album"] for pos in positions],
                "uris": uris_in_group,
                "has_identical_uris": has_identical_uris
            }
            
            duplicate_groups.append(duplicate_group)
            
            if debug:
                logger.info(f"Duplicate group: '{positions[0]['name']}' - {positions[0]['artist']}")
                logger.info(f"  {len(positions)} occurrences at positions: {[pos['position'] for pos in positions]}")
                logger.info(f"  URIs: {uris_in_group}")
                logger.info(f"  Has identical URIs: {has_identical_uris}")
                logger.info(f"  Will keep position {positions[0]['position']}, remove positions {[pos['position'] for pos in positions[1:]]}")

            # Keep the first occurrence (topmost position = lowest position number)
            # Remove all others (positions[1:])
            for pos_info in positions[1:]:
                duplicate_positions_to_remove.append({
                    "position": pos_info["position"],
                    "uri": pos_info["uri"],
                    "name": pos_info["name"],
                    "artist": pos_info["artist"],
                    "track_key": track_key
                })

    # Step 4: Separate duplicates by URI uniqueness
    # Group removals by whether they have identical URIs with other tracks to remove
    unique_uri_removals = []  # Can use position-specific removal
    identical_uri_groups = defaultdict(list)  # Need remove-all + re-add approach
    
    # Check each track to remove against all tracks in the playlist
    for removal in duplicate_positions_to_remove:
        uri = removal["uri"]
        # Count how many times this URI appears in the ENTIRE playlist
        total_uri_occurrences = len(uri_usage[uri])
        
        if total_uri_occurrences > 1:
            # This URI appears multiple times - need special handling
            identical_uri_groups[uri].append(removal)
        else:
            # This URI is unique - safe to use position-specific removal
            unique_uri_removals.append(removal)
    
    # Sort unique URI removals by position in descending order (bottom to top)
    unique_uri_removals.sort(key=lambda x: x["position"], reverse=True)
    
    if debug:
        logger.info(f"\nRemoval strategy:")
        logger.info(f"  Tracks with unique URIs (position-specific removal): {len(unique_uri_removals)}")
        logger.info(f"  Tracks with identical URIs (remove-all + re-add): {len(identical_uri_groups)} groups")
        for uri, group in identical_uri_groups.items():
            logger.info(f"    URI {uri}: {len(group)} duplicates to handle")
    
    if dry_run:
        if debug:
            logger.info("\n=== DRY RUN MODE - No actual changes will be made ===")
            logger.info(f"Would remove {len(duplicate_positions_to_remove)} tracks total:")
            logger.info(f"  - {len(unique_uri_removals)} via position-specific removal")
            logger.info(f"  - {sum(len(group) for group in identical_uri_groups.values())} via remove-all + re-add")
            
            if unique_uri_removals:
                logger.info("\nPosition-specific removals:")
                for item in unique_uri_removals[:5]:  # Show first 5
                    logger.info(f"  Position {item['position']}: '{item['name']}' - {item['artist']}")
                if len(unique_uri_removals) > 5:
                    logger.info(f"  ... and {len(unique_uri_removals) - 5} more")
            
            if identical_uri_groups:
                logger.info("\nRemove-all + re-add groups:")
                for uri, group in list(identical_uri_groups.items())[:3]:  # Show first 3 groups
                    track_info = group[0]  # All have same track info
                    # Find the position to keep (minimum position among all occurrences of this URI)
                    all_positions = [occ["position"] for occ in uri_usage[uri]]
                    keep_position = min(all_positions)
                    logger.info(f"  '{track_info['name']}' - {track_info['artist']} (URI: {uri})")
                    logger.info(f"    Will remove all {len(uri_usage[uri])} occurrences and re-add at position {keep_position}")
                if len(identical_uri_groups) > 3:
                    logger.info(f"  ... and {len(identical_uri_groups) - 3} more groups")
        
        return {
            "total_tracks": len(tracks),
            "unique_tracks": len(track_positions),
            "duplicates_found": len(duplicate_groups),
            "tracks_removed": 0,
            "duplicate_groups": duplicate_groups,
            "planned_removals": duplicate_positions_to_remove,
            "unique_uri_removals": unique_uri_removals,
            "identical_uri_groups": dict(identical_uri_groups),
            "dry_run": True,
            "uri_usage": dict(uri_usage),
            "initial_snapshot": initial_snapshot
        }
    
    # Actual removal process - simulation approach
    removed_count = 0
    removal_errors = []
    successful_removals = []
    
    if debug:
        logger.info(f"\n=== Starting actual removal process ===")
    
    # Create initial playlist simulation (list of URIs)
    playlist_simulation = [item["track"]["uri"] if item["track"] else None for item in tracks]
    
    # Plan all operations using simulation
    operations_to_execute = []  # List of (operation_type, uri, positions, target_position)
    
    if debug:
        logger.info(f"Created playlist simulation with {len(playlist_simulation)} tracks")
        logger.info(f"Planning operations for {len(identical_uri_groups)} identical URI groups...")
    
    # Process each identical URI group in simulation
    for uri, removal_group in identical_uri_groups.items():
        try:
            # Find current positions of this URI in simulation
            current_positions = find_current_positions(playlist_simulation, uri)
            
            if not current_positions:
                if debug:
                    logger.warning(f"URI {uri} not found in simulation - skipping")
                continue
            
            # Determine position to keep (minimum position)
            keep_position = min(current_positions)
            
            if debug:
                track_info = removal_group[0]
                logger.info(f"\nSimulating URI group: '{track_info['name']}' - {track_info['artist']}")
                logger.info(f"  URI: {uri}")
                logger.info(f"  Current positions in simulation: {current_positions}")
                logger.info(f"  Will keep at position: {keep_position}")
            
            # Record operation for execution
            operations_to_execute.append({
                "type": "remove_all_readd",
                "uri": uri,
                "removal_group": removal_group,
                "current_positions": current_positions.copy(),
                "target_position": keep_position
            })
            
            # Simulate the operation
            playlist_simulation = simulate_remove_positions(playlist_simulation, current_positions)
            playlist_simulation = simulate_add_at_position(playlist_simulation, uri, keep_position)
            
            if debug:
                logger.info(f"  Simulation updated - playlist now has {len(playlist_simulation)} tracks")
            
        except Exception as e:
            error_msg = f"Error simulating URI group {uri}: {e}"
            logger.error(error_msg)
            for item in removal_group:
                removal_errors.append({
                    "position": item["position"],
                    "error": str(e),
                    "type": "simulation_error"
                })
    
    # Plan unique URI removals
    current_unique_uri_removals = []
    for item in unique_uri_removals:
        # Find current position in simulation
        current_positions = find_current_positions(playlist_simulation, item["uri"])
        if current_positions:
            # Should only be one position for unique URIs
            current_position = current_positions[0]
            operations_to_execute.append({
                "type": "remove_specific",
                "uri": item["uri"],
                "removal_info": item,
                "current_position": current_position,
                "original_position": item["position"]
            })
            
            # Simulate removal
            playlist_simulation = simulate_remove_positions(playlist_simulation, [current_position])
            current_unique_uri_removals.append(item)
    
    if debug:
        logger.info(f"\nSimulation complete. Planned {len(operations_to_execute)} operations:")
        identical_ops = [op for op in operations_to_execute if op["type"] == "remove_all_readd"]
        unique_ops = [op for op in operations_to_execute if op["type"] == "remove_specific"]
        logger.info(f"  - {len(identical_ops)} identical URI groups (remove-all + re-add)")
        logger.info(f"  - {len(unique_ops)} unique URI removals")
    
    # Execute all planned operations
    if debug:
        logger.info(f"\n=== Executing planned operations ===")
    
    for i, operation in enumerate(operations_to_execute):
        try:
            # Check if playlist was modified by someone else
            current_playlist = rate_limited_call(sp.playlist, playlist_id, fields="snapshot_id")
            current_snapshot = current_playlist["snapshot_id"]
            
            if current_snapshot != initial_snapshot:
                error_msg = f"Playlist snapshot changed from {initial_snapshot} to {current_snapshot}. Aborting to prevent data loss."
                logger.error(error_msg)
                break
            
            if operation["type"] == "remove_all_readd":
                # Handle identical URI group
                uri = operation["uri"]
                removal_group = operation["removal_group"]
                target_position = operation["target_position"]
                
                if debug:
                    track_info = removal_group[0]
                    logger.info(f"\nExecuting operation {i+1}/{len(operations_to_execute)}: '{track_info['name']}' - {track_info['artist']}")
                    logger.info(f"  Removing all occurrences of URI: {uri}")
                
                # Remove ALL occurrences
                rate_limited_call(
                    sp.playlist_remove_all_occurrences_of_items,
                    playlist_id,
                    [uri]
                )
                
                # Re-add at calculated position
                if debug:
                    logger.info(f"  Re-adding at position: {target_position}")
                
                rate_limited_call(
                    sp.playlist_add_items,
                    playlist_id,
                    [uri],
                    position=target_position
                )
                
                removed_count += len(removal_group)
                successful_removals.extend(removal_group)
                
                if debug:
                    logger.info(f"  ✓ Successfully processed identical URI group")
            
            elif operation["type"] == "remove_specific":
                # Handle unique URI removal
                uri = operation["uri"]
                removal_info = operation["removal_info"]
                current_position = operation["current_position"]
                original_position = operation["original_position"]
                
                if debug:
                    logger.info(f"\nExecuting operation {i+1}/{len(operations_to_execute)}: Remove '{removal_info['name']}' - {removal_info['artist']}")
                    logger.info(f"  Original position: {original_position}, Current position: {current_position}")
                
                # Verify track is at expected position
                current_tracks = rate_limited_call(sp.playlist_items, playlist_id, limit=1, offset=current_position)
                
                if not current_tracks["items"]:
                    error_msg = f"No track found at position {current_position}"
                    logger.error(error_msg)
                    removal_errors.append({
                        "position": current_position,
                        "error": error_msg,
                        "type": "position_not_found"
                    })
                    continue
                
                current_track = current_tracks["items"][0]["track"]
                if current_track["uri"] != uri:
                    error_msg = f"Track mismatch at position {current_position}. Expected {uri}, found {current_track['uri']}"
                    logger.warning(error_msg)
                    removal_errors.append({
                        "position": current_position,
                        "error": error_msg,
                        "type": "track_mismatch"
                    })
                    continue
                
                # Remove the track
                rate_limited_call(
                    sp.playlist_remove_specific_occurrences_of_items,
                    playlist_id,
                    [{"uri": uri, "positions": [current_position]}]
                )
                
                removed_count += 1
                successful_removals.append(removal_info)
                
                if debug:
                    logger.info(f"  ✓ Successfully removed track")
            
            # Update snapshot for next operation
            updated_playlist = rate_limited_call(sp.playlist, playlist_id, fields="snapshot_id")
            initial_snapshot = updated_playlist["snapshot_id"]
            
        except Exception as e:
            error_msg = f"Error executing operation {i+1}: {e}"
            logger.error(error_msg)
            if operation["type"] == "remove_all_readd":
                for item in operation["removal_group"]:
                    removal_errors.append({
                        "position": item["position"],
                        "error": str(e),
                        "type": "api_error"
                    })
            else:
                removal_errors.append({
                    "position": operation["current_position"],
                    "error": str(e),
                    "type": "api_error"
                })

    # Final snapshot check
    final_playlist = rate_limited_call(sp.playlist, playlist_id, fields="snapshot_id,tracks.total")
    final_snapshot = final_playlist["snapshot_id"]
    final_track_count = final_playlist["tracks"]["total"]
    
    if debug:
        logger.info(f"\n=== Removal Complete ===")
        logger.info(f"Successfully removed: {removed_count} tracks")
        logger.info(f"Errors encountered: {len(removal_errors)}")
        logger.info(f"Final track count: {final_track_count} (was {len(tracks)})")
        logger.info(f"Final snapshot: {final_snapshot}")
    
    return {
        "total_tracks": len(tracks),
        "final_track_count": final_track_count,
        "unique_tracks": len(track_positions),
        "duplicates_found": len(duplicate_groups),
        "tracks_removed": removed_count,
        "duplicate_groups": duplicate_groups,
        "removal_errors": removal_errors,
        "successful_removals": successful_removals,
        "unique_uri_removals": unique_uri_removals,
        "identical_uri_groups": dict(identical_uri_groups),
        "dry_run": False,
        "uri_usage": dict(uri_usage),
        "initial_snapshot": initial_snapshot,
        "final_snapshot": final_snapshot
    }


