import aubio
import librosa
import numpy as np
import statistics
# function will probably take the file and the chosen string to tune as input from trigger/queue. 
input_file =  "input_songs/tuned_g_string.wav"
src = aubio.source(input_file)

#samplerate = 44100
#hop_size = 512
pitch = aubio.pitch("yinfft", 4096, src.hop_size, src.samplerate)
pitch.set_unit("Hz")
pitch.set_tolerance(0.8)
skip_frames = 10
buffer = []
sampling = True
frequency_limit = 1500 #this goes beyond the highest possible frequency of any guitar, so it can filter out any outliers
standard_tuning = { #+- 5 cents for a good range
    "e": { "low": 328.68, "high": 330.58}, #E4
    "B": { "low": 246.23, "high": 247.65}, #B3
    "G": { "low": 195.43, "high": 196.57}, #G3
    "D": { "low": 146.41, "high": 147.25}, #D3
    "A": { "low": 109.68, "high": 110.32}, #A2
    "E": { "low": 82.17, "high": 82.65} #E2
}
chosen_string = "G" #test string
while sampling:
    samples, read = src()

    if read == 0: #if no sound, break the loop
        break
    frequency_value = pitch(samples)[0]
    confidence = pitch.get_confidence()
    if skip_frames > 0:
        skip_frames -= 1 #skips the first 10 frames so that the algorithm reads from the stable part of the note
        continue
    if frequency_value > 0 and np.isnan(frequency_value) == False and frequency_value < frequency_limit: #sometimes program recorded NaN values
        buffer.append(frequency_value)
    elif len(buffer) == 0: #in case no value is added
        continue
if len(buffer) > 0:
    chosen_frequency_value = np.median(buffer) #handles outliers
    midi_value = round(librosa.hz_to_midi(chosen_frequency_value))
    note = librosa.midi_to_note(midi_value)
    print(f"note: {note}, midi: {midi_value}, frequency: {chosen_frequency_value}, confidence: {confidence}")

    tuned_frequency = standard_tuning[chosen_string]
    if chosen_frequency_value < tuned_frequency["low"]:
        print("too low, tune up")
    elif chosen_frequency_value > tuned_frequency["high"]:
        print("too high, tune down")
    else:
        print("string in tune")




