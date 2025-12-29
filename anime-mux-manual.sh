#!/usr/bin/env bash
# Anime Multi-Audio Mux Tool - Perfected Version (Smart Storage)
# Erstellt MKV-Dateien und berechnet den echten (Netto) Speicherplatzgewinn.

SERIES_DIR="/media/hdd/series"
CONTAINER="mkvtoolnix"
CONTAINER_PATH="/storage"

# Funktion zur smarten Formatierten der Speichergröße
format_size() {
    local bytes=$1
    if [[ $bytes -lt 1048576 ]]; then
        echo "$((bytes / 1024)) KB"
    elif [[ $bytes -lt 1073741824 ]]; then
        echo "$((bytes / 1024 / 1024)) MB"
    else
        # Rechnet GB mit einer Nachkommastelle
        echo "scale=2; $bytes / 1024 / 1024 / 1024" | bc | sed 's/\./,/' | xargs -I {} echo "{} GB"
    fi
}

echo "═══════════════════════════════════════════════════"
echo "        Anime Multi-Audio Mux Tool v2.1"
echo "═══════════════════════════════════════════════════"
echo "Scanning $SERIES_DIR for episodes with multiple versions..."
echo ""

# Episode zählen
episode_count=0
while IFS= read -r dub; do
    dir="$(dirname "$dub")"
    base="$(basename "$dub" | sed -E 's/ - \([^)]+\)\.mp4$//')"
    out="$dir/${base}.mkv"
    [[ -f "$out" ]] && continue
    versions=0
    [[ -f "$dir/${base} - (German Dub).mp4" ]] && ((versions++))
    [[ -f "$dir/${base} - (German Sub).mp4" ]] && ((versions++))
    [[ -f "$dir/${base} - (English Dub).mp4" ]] && ((versions++))
    [[ -f "$dir/${base} - (English Sub).mp4" ]] && ((versions++))
    [[ $versions -ge 2 ]] && ((episode_count++))
done < <(find "$SERIES_DIR" -name "*German Dub*.mp4" -o -name "*English Dub*.mp4" 2>/dev/null | sort -u)

if [[ $episode_count -eq 0 ]]; then
    echo "No episodes with multiple versions found."
    exit 0
fi

echo "Found: $episode_count episode(s) to mux"
echo ""
read -p "🗑️  Delete old MP4 files automatically after muxing? (y/N): " delete_all < /dev/tty
echo ""

processed=0
skipped=0
total_net_gain=0

while IFS= read -r dub; do
    dir="$(dirname "$dub")"
    base="$(basename "$dub" | sed -E 's/ - \([^)]+\)\.mp4$//')"
    out="$dir/${base}.mkv"
    
    if [[ -f "$out" ]]; then
        ((skipped++))
        continue
    fi
    
    versions=0
    has_german_dub=false; has_german_sub=false; has_english_dub=false; has_english_sub=false
    
    [[ -f "$dir/${base} - (German Dub).mp4" ]] && { ((versions++)); has_german_dub=true; }
    [[ -f "$dir/${base} - (German Sub).mp4" ]] && { ((versions++)); has_german_sub=true; }
    [[ -f "$dir/${base} - (English Dub).mp4" ]] && { ((versions++)); has_english_dub=true; }
    [[ -f "$dir/${base} - (English Sub).mp4" ]] && { ((versions++)); has_english_sub=true; }
    
    if [[ $versions -lt 2 ]]; then
        ((skipped++))
        continue
    fi
    
    echo "════════════════════════════════════════════════════"
    echo "📦 Episode: $base"
    echo "   Available versions: $versions"
    echo ""
    
    relative_dir="${dir#$SERIES_DIR}"
    container_dir="$CONTAINER_PATH$relative_dir"
    container_out="$container_dir/$(basename "$out")"
    
    mux_cmd="mkvmerge -o '$container_out'"
    
    if $has_german_dub; then
        mux_cmd="$mux_cmd --language 1:de --track-name 1:'German' '$container_dir/${base} - (German Dub).mp4'"
        video_source="german_dub"
    elif $has_english_dub; then
        mux_cmd="$mux_cmd --language 1:en --track-name 1:'English' '$container_dir/${base} - (English Dub).mp4'"
        video_source="english_dub"
    elif $has_german_sub; then
        mux_cmd="$mux_cmd --language 1:ja --track-name 1:'Japanese' '$container_dir/${base} - (German Sub).mp4'"
        video_source="german_sub"
    else
        mux_cmd="$mux_cmd --language 1:ja --track-name 1:'Japanese' '$container_dir/${base} - (English Sub).mp4'"
        video_source="english_sub"
    fi
    
    japanese_added=false
    if [[ "$video_source" != "german_sub" ]] && $has_german_sub && ! $japanese_added; then
        mux_cmd="$mux_cmd -a 1 -D -S --language 1:ja --track-name 1:'Japanese' '$container_dir/${base} - (German Sub).mp4'"
        japanese_added=true
    elif [[ "$video_source" != "english_sub" ]] && $has_english_sub && ! $japanese_added; then
        mux_cmd="$mux_cmd -a 1 -D -S --language 1:ja --track-name 1:'Japanese' '$container_dir/${base} - (English Sub).mp4'"
        japanese_added=true
    fi
    
    if [[ "$video_source" != "english_dub" ]] && $has_english_dub; then
        mux_cmd="$mux_cmd -a 1 -D -S --language 1:en --track-name 1:'English' '$container_dir/${base} - (English Dub).mp4'"
    fi
    
    echo "⚙️  Starting mux..."
    docker exec "$CONTAINER" sh -c "$mux_cmd" 2>&1 | grep -v "^Warning:" | grep -v "^mkvmerge v"
    exitcode=$?
    
    if [[ $exitcode -le 1 ]] && [[ -f "$out" ]]; then
        echo "✅ Successfully muxed"
        ((processed++))
        
        # Neue MKV Größe messen
        mkv_size=$(stat -f%z "$out" 2>/dev/null || stat -c%s "$out" 2>/dev/null)

        if [[ "$delete_all" == "y" || "$delete_all" == "Y" ]]; then
            deleted_size_episode=0
            trickplay_cleaned=0
            
            # Dateien löschen und deren Größe sammeln
            for suffix in "(German Dub)" "(German Sub)" "(English Dub)" "(English Sub)"; do
                file="$dir/${base} - $suffix.mp4"
                if [[ -f "$file" ]]; then
                    size=$(stat -f%z "$file" 2>/dev/null || stat -c%s "$file" 2>/dev/null)
                    deleted_size_episode=$((deleted_size_episode + size))
                    rm -f "$file"
                    # Trickplay Ordner löschen
                    if [[ -d "$file.trickplay" ]]; then
                        rm -rf "$file.trickplay"
                        ((trickplay_cleaned++))
                    fi
                fi
            done
            
            # Netto Ersparnis berechnen (Gelöscht minus neu Erstellt)
            net_gain_episode=$((deleted_size_episode - mkv_size))
            total_net_gain=$((total_net_gain + net_gain_episode))
            
            echo "🗑️  MP4s deleted (Net gain: $(format_size $net_gain_episode))"
            [[ $trickplay_cleaned -gt 0 ]] && echo "🧹 $trickplay_cleaned trickplay folder(s) cleaned"
        else
            echo "💾 MP4s kept (New MKV size: $(format_size $mkv_size))"
        fi
    else
        echo "❌ ERROR during muxing (exit code: $exitcode)!"
    fi
    echo ""
done < <(find "$SERIES_DIR" -name "*German Dub*.mp4" -o -name "*English Dub*.mp4" 2>/dev/null | sort -u)

echo "═══════════════════════════════════════════════════"
echo "✨ Done!"
echo "   Processed: $processed episode(s)"
echo "   Skipped: $skipped"

if [[ "$delete_all" == "y" || "$delete_all" == "Y" ]]; then
    echo "   Total Net Space Gained: $(format_size $total_net_gain)"
fi
echo "═══════════════════════════════════════════════════"
