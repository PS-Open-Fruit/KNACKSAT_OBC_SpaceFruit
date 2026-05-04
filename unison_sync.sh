# IP=100.1.1.1
IP=192.168.28.39
unison ./eps_and_payload_emulator/kiss_file_transfer/ ssh://bipoe@${IP}//home//bipoe//payload_emulator// \
    -repeat 2 \
    -batch \
    -ignore 'Name .venv' \
    -prefer ./eps_and_payload_emulator/kiss_file_transfer/