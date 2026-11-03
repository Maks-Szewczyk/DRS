import os
import aubio
import sys
import types
sys.modules["__main__"] = types.ModuleType("__main__")
import librosa
import soundfile as sf
import numpy as np
import json
import logging
import azure.functions as func
from azure.storage.blob import BlobServiceClient
from azure.data.tables import TableClient
from azure.core import MatchConditions

app = func.FunctionApp()

#job ID FUNCTION
def get_job_id():
    table = TableClient.from_connection_string(conn_str=os.environ["AzureWebJobsStorage"], table_name="Jobs")
    entity = table.get_entity("User", "Job")
    entity["job_id"] +=1
    table.update_entity(entity=entity,etag=entity.metadata["etag"], match_condition=MatchConditions.IfNotModified)
    return entity["job_id"]


@app.function_name(name= "QueueInput")
@app.route(route = "submit_note", methods = ["POST"]) #post method to submit a note to the queue.
@app.queue_output(arg_name = "queue_msg",
                  queue_name = "tuner-queue",
                  connection = "AzureWebJobsStorage")

#FUNCTION 1
def submit_tune_job(req: func.HttpRequest, queue_msg: func.Out[str]) -> func.HttpResponse:
    logging.info("Recieved a job request")
    #validation
    try:
        #requesting data for validation
        data = req.get_json()
        audio_file = data.get("audio_file")
        desired_note = data.get("desired_note")

        if not audio_file or not desired_note: #if either are empty, raise an error.
            raise ValueError("Missing required fields: audio_file and desired_note must be provided.")

    except ValueError:
        return func.HttpResponse("Invalid data", status_code=400) #400 code = wont process the request
    job_id = get_job_id()
    job_data = { #data to be sent to the queue.
        "job_id": job_id,
        "audio_file": audio_file,
        "desired_note": desired_note,
        "processed": False
    }

    queue_msg.set(json.dumps(job_data))

    return func.HttpResponse(body = json.dumps({"job_id": job_id}), status_code=202, mimetype="application/json") #202 code = accepted for processing




#FUNCTION 2
# function will probably take the file and the chosen string to tune as input from trigger/queue. 
@app.function_name(name = "QueueOutput")
@app.queue_trigger(arg_name = "queue_msg",
                   queue_name = "tuner-queue",
                   connection = "AzureWebJobsStorage")

def process_audio(queue_msg: func.QueueMessage) -> None:
    logging.info("Processing audio file from queue")
    data = json.loads(queue_msg.get_body().decode('utf-8'))
    input_file = data.get("audio_file")
    target_note = data.get("desired_note")
    #followed tutorial given by Microsoft: https://learn.microsoft.com/en-us/azure/storage/blobs/storage-blob-download-python
    connection_string = os.environ["AzureWebJobsStorage"]

    blob_service_client = BlobServiceClient.from_connection_string(
        connection_string
    )

    blob_service_client = BlobServiceClient.from_connection_string(connection_string)
    blob_client = blob_service_client.get_blob_client(container="ready-audio", blob=input_file)
    working_file = f"/tmp/{os.path.basename(input_file)}"
    with open(working_file, "wb") as f:
        download_stream = blob_client.download_blob()
        f.write(download_stream.readall())
        logging.info("Downloaded audio file from blob storage")

    src = aubio.source(working_file)
    #samplerate = 44100
    #hop_size = 512
    pitch = aubio.pitch("yinfft", 4096, src.hop_size, src.samplerate)
    pitch.set_unit("Hz")
    pitch.set_tolerance(0.8)
    skip_frames = 10
    buffer = []
    frequency_limit = 1500 #this goes beyond the highest possible frequency of any guitar, so it can filter out any outliers

    while True:
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

        midi_pitch = librosa.note_to_midi(target_note) - midi_value
        y, sr = librosa.load(working_file, sr = None)
        if abs(midi_pitch) > 0.05: #if midi change above 5 cents 
            y_harmonic, y_percussive = librosa.effects.hpss(y)
            harmonic_shifted = librosa.effects.pitch_shift(y_harmonic, sr=sr, n_steps = midi_pitch)
            if abs(midi_pitch) > 12:
                y_shifted = harmonic_shifted + (y_percussive * 0.5) #reduce picking sound by half for good measure to avoid distortion.
                print("Pitch shift above 12 semitones, reducing percussive component to avoid artifacts")
            else:
                y_shifted = harmonic_shifted + y_percussive
        else:
            y_shifted = y
            print("No pitch shift needed, already in tune")
    else:
        raise ValueError("No valid frequency values found in the audio file.")
    job_id = data["job_id"]
    output_file = f"/tmp/shifted_string.wav"
    output_blob_name = f"shifted_string_{job_id}.wav"
    sf.write(output_file, y_shifted, sr)
    logging.info("Pitch shifting complete, saving output file")
    blob_service_client = BlobServiceClient.from_connection_string(connection_string)
    blob_client = blob_service_client.get_blob_client(container="processed-audio", blob=output_blob_name)
    with open(output_file, "rb") as f:
        blob_client.upload_blob(f, overwrite=False)
    logging.info("Upload Successful")




