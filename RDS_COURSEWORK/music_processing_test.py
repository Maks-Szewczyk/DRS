import aubio
import librosa
import numpy as np
import matplotlib.pyplot as plt
import statistics

input_file = "input_songs/wake_me_up_when_september_ends.wav"
src = aubio.source(input_file)

#samplerate = 44100
#hop_size = 512
onset = aubio.onset("default", 4096, src.hop_size, src.samplerate)
pitch = aubio.pitch("yin", 4096, src.hop_size, src.samplerate)

pitch.set_unit("Hz")
pitch.set_tolerance(0.8)
onset.set_threshold(0.7)
guitar_strings = { # notes and their corresponding midi values
    "E":40, #E2
    "A":45, #A2
    "D":50, #D3
    "G":55, #G3
    "B":59, #B3
    "e":64  #E4
}


limit = 100
midi_value = np.zeros(limit)
confidence_values = np.zeros(limit)
notes = np.zeros(limit, dtype=object)
i = 0
while True:
    samples, read = src()
    pitch_value = pitch(samples)[0]
    confidence = pitch.get_confidence()
    is_onset = onset(samples)
    onset_time = onset.get_last_s()
    if pitch_value > 0 and is_onset:
        midi_note = round(librosa.hz_to_midi(pitch_value))
        if i < limit:
            midi_value[i] = midi_note
            notes[i] = librosa.midi_to_note(midi_note)
            confidence_values[i] = confidence
            i+=1
    if read < src.hop_size:
        break
for note,midi,confidence in zip(notes, midi_value, confidence_values):
    print(f"note: {note}, midi: {midi}, confidence: {confidence}")
    continue
