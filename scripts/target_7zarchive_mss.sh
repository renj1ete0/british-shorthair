#!/bin/bash
export_dir="export_mss"
log_file="7z_export.json"

current_date=$(date -d "yesterday" +%Y-%m-%d)

cp "logs/logs_$current_date.json" "$export_dir/$current_date"
cd $export_dir

folder_to_7z="$current_date"
current_datetime=$(date "+%Y-%m-%d %H:%M:%S")

if [ -d "$folder_to_7z" ]; then
    7z a $current_date.7z $folder_to_7z

    if [ $? -eq 0 ]; then
        echo "[$current_datetime] 7z archive $folder_to_7z.7z created successfully." >> "$log_file"
        rm -r "$folder_to_7z"
    else
        echo "[$current_datetime] Error creating 7z archive $folder_to_7z.7z." >> "$log_file"
    fi

else
    echo echo "[$current_datetime] Error creating 7z archive. $folder_to_7z does not exist" >> "$log_file"
fi