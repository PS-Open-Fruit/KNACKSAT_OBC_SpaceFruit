unison ./eps_and_payload_emulator/kiss_file_transfer/ ssh://bipoe@100.1.1.1//home//bipoe//payload_emulator// \
    -prefer ./eps_and_payload_emulator/kiss_file_transfer/ \
    -repeat 2 \
    -batch \
    -ignore 'Name .venv'