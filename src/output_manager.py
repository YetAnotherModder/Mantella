import openai
from aiohttp import ClientSession
import asyncio
import os
import wave
import logging
import time
import shutil
import src.utils as utils
import unicodedata
import re
import numpy as np
import pygame
import sys
import math
from scipy.io import wavfile

class ChatManager:
    def __init__(self, game_state_manager, config, encoding):
        self.game = config.game
        self.game_state_manager = game_state_manager
        self.mod_folder = config.mod_path
        self.max_response_sentences = config.max_response_sentences
        self.llm = config.llm
        self.alternative_openai_api_base = config.alternative_openai_api_base
        self.temperature = config.temperature
        self.top_p = config.top_p
        self.stop = config.stop
        self.frequency_penalty = config.frequency_penalty
        self.max_tokens = config.max_tokens
        self.language = config.language
        self.encoding = encoding
        self.add_voicelines_to_all_voice_folders = config.add_voicelines_to_all_voice_folders
        self.offended_npc_response = config.offended_npc_response
        self.forgiven_npc_response = config.forgiven_npc_response
        self.follow_npc_response = config.follow_npc_response
        self.wait_time_buffer = config.wait_time_buffer
        self.root_mod_folder = config.game_path

        self.character_num = 0
        self.active_character = None

        self.wav_file = f'MantellaDi_MantellaDialogu_00001D8B_1.wav'
        self.lip_file = f'MantellaDi_MantellaDialogu_00001D8B_1.lip'

        self.f4_use_wav_file1 = True
        self.f4_wav_file1 = f'MutantellaOutput1.wav'
        self.f4_wav_file2 = f'MutantellaOutput2.wav'
        self.f4_lip_file = f'00001ED2_1.lip'
        self.FO4Volume = config.FO4Volume

        self.end_of_sentence_chars = ['.', '?', '!', ':', ';']
        self.end_of_sentence_chars = [unicodedata.normalize('NFKC', char) for char in self.end_of_sentence_chars]

        self.sentence_queue = asyncio.Queue()

    def pygame_initialize(self):
        if self.game == "Fallout4" or self.game == "Fallout4VR":
            # Ensure pygame is initialized
            if not pygame.get_init():
                pygame.init()

            # Explicitly initialize the pygame mixer
            if not pygame.mixer.get_init():
                pygame.mixer.init(frequency=22050, size=-16, channels=2)  # Adjust these values as necessary
            logging.info('pygame is ')
            logging.info(pygame.__version__)


    async def get_audio_duration(self, audio_file):
        """Check if the external software has finished playing the audio file"""

        with wave.open(audio_file, 'r') as wf:
            frames = wf.getnframes()
            rate = wf.getframerate()

        # wait `buffer` seconds longer to let processes finish running correctly
        duration = frames / float(rate) + self.wait_time_buffer
        return duration
    

    def setup_voiceline_save_location(self, in_game_voice_folder):
        """Save voice model folder to Mantella Spell if it does not already exist"""
        self.in_game_voice_model = in_game_voice_folder

        in_game_voice_folder_path = f"{self.mod_folder}/{in_game_voice_folder}/"
        if not os.path.exists(in_game_voice_folder_path):
            os.mkdir(in_game_voice_folder_path)

            # copy voicelines from one voice folder to this new voice folder
            # this step is needed for Skyrim/Fallout4 to acknowledge the folder
            if self.game == "Fallout4" or self.game == "Fallout4VR":
                example_folder = f"{self.mod_folder}/maleboston/"
            else:
                example_folder = f"{self.mod_folder}/MaleNord/"
            for file_name in os.listdir(example_folder):
                source_file_path = os.path.join(example_folder, file_name)

                if os.path.isfile(source_file_path):
                    shutil.copy(source_file_path, in_game_voice_folder_path)

            self.game_state_manager.write_game_info('_mantella_status', 'Error with Mantella.exe. Please check MantellaSoftware/logging.log')
            logging.warn(f"Unknown NPC detected. This NPC will be able to speak once you restart {self.game}. To learn how to add memory, a background, and a voice model of your choosing to this NPC, see here: https://github.com/art-from-the-machine/Mantella#adding-modded-npcs")
            time.sleep(5)
            return True
        return False


    @utils.time_it
    def save_files_to_voice_folders(self, queue_output):
        """Save voicelines and subtitles to the correct game folders"""

        audio_file, subtitle = queue_output

        if self.add_voicelines_to_all_voice_folders == '1':
            for sub_folder in os.scandir(self.mod_folder):
                if sub_folder.is_dir():
                    #if the game is Fallout 4 only copy the lip file
                    if self.game =="Fallout4" or self.game == "Fallout4VR":
                        shutil.copyfile(audio_file.replace(".wav", ".lip"), f"{sub_folder.path}/{self.f4_lip_file}")
                    #copy both the wav file and lip file if the game isn't Fallout4 or Fallout 4 VR
                    else:    
                        shutil.copyfile(audio_file, f"{sub_folder.path}/{self.wav_file}")
                        shutil.copyfile(audio_file.replace(".wav", ".lip"), f"{sub_folder.path}/{self.lip_file}")
        else:

            if self.game =="Fallout4" or self.game == "Fallout4VR":
            #if the game is Fallout 4 only copy the lip file
                shutil.copyfile(audio_file.replace(".wav", ".lip"), f"{self.mod_folder}/{self.active_character.in_game_voice_model}/{self.f4_lip_file}")
            #copy both the wav file and lip file if the game isn't Fallout4 or Fallout 4 VR
            else: 
                shutil.copyfile(audio_file, f"{self.mod_folder}/{self.active_character.in_game_voice_model}/{self.wav_file}")
                shutil.copyfile(audio_file.replace(".wav", ".lip"), f"{self.mod_folder}/{self.active_character.in_game_voice_model}/{self.lip_file}")

        logging.info(f"{self.active_character.name} (character {self.character_num}) should speak")
        if self.character_num == 0:
            self.game_state_manager.write_game_info('_mantella_say_line', subtitle.strip())
            if self.game =="Fallout4" or self.game =="Fallout4VR":
                self.play_adjusted_volume(audio_file)

        else:
            say_line_file = '_mantella_say_line_'+str(self.character_num+1)
            self.game_state_manager.write_game_info(say_line_file, subtitle.strip())
            if self.game =="Fallout4" or self.game =="Fallout4VR":
                self.play_adjusted_volume(audio_file)

    def play_adjusted_volume(self, wav_file_path):
        FO4Volume_scale = self.FO4Volume / 100.0  # Normalize to 0.0-1.0
        logging.info("Waiting for _mantella_audio_ready.txt to be set with the audio array in Fallout 4 directory")
        while True:
            with open(f'{self.root_mod_folder}/_mantella_audio_ready.txt', 'r', encoding='utf-8') as f:
                audio_array_str = f.read().strip()
                #check if a value is entered in the audio array (necessary to prevent Mantella trying to read an empty file)
                if audio_array_str.lower() != 'false' and audio_array_str:
                    try:
                        # Parse the data
                        npc_distance, playerPosX, playerPosY, game_angle_z, targetPosX, targetPosY = map(float, audio_array_str.split(','))
                        player_pos = (playerPosX, playerPosY)
                        target_pos = (targetPosX, targetPosY)
                        
                        # Calculate the relative angle
                        relative_angle = self.calculate_relative_angle(player_pos, target_pos, game_angle_z)

                        # Normalize the relative angle between -180 and 180
                        normalized_angle = relative_angle % 360
                        if normalized_angle > 180:
                            normalized_angle -= 360  # Adjust angles to be within [-180, 180]

                        # Calculate volume scale based on the normalized angle
                        if normalized_angle >= -90 and normalized_angle <= 90:  # Front half
                            # Linear scaling: Full volume at 0 degrees, decreasing to 50% volume at 90 degrees to either side
                            volume_scale_left = 0.5 + normalized_angle / 90 * 0.5
                            volume_scale_right = 0.5 - normalized_angle / 90 * 0.5
                        elif normalized_angle > 90 and normalized_angle < 180:
                            volume_scale_left = 90 / normalized_angle
                            volume_scale_right = 1- 90 / normalized_angle
                        elif normalized_angle > -180 and normalized_angle < -90:
                            volume_scale_left = 1- 90 / abs(normalized_angle)
                            volume_scale_right = 90 / abs(normalized_angle)
                        else:  # failsafe if for some reason an unmanaged number is entered
                            volume_scale_left = 0.5
                            volume_scale_right = 0.5

                        # Apply the calculated scale differently to left and right channels based on angle direction
                        #if normalized_angle >= 0:  # Turning right
                        #    volume_scale_left = volume_scale
                        #    volume_scale_right = 1 - abs(normalized_angle) / 90 * 0.5  # Decrease right volume as angle increases
                        #else:  # Turning left
                        #    volume_scale_right = volume_scale
                    #    volume_scale_left = 1 - abs(normalized_angle) / 90 * 0.5  # Decrease left volume as angle decreases

                        # Ensure volumes don't drop below a threshold, for example, 0.1, if you want to keep a minimum volume level
                        min_volume_threshold = 0.1
                        volume_scale_left = max(volume_scale_left, min_volume_threshold)
                        volume_scale_right = max(volume_scale_right, min_volume_threshold)

                        if npc_distance > 0:
                            distance_factor = max(0, 1 - (npc_distance / 4000))
                        else:
                            distance_factor=1

                        # Load the WAV file
                        sound = pygame.mixer.Sound(wav_file_path)
                        original_audio_array = pygame.sndarray.array(sound)
                        
                        if original_audio_array.ndim == 1:  # Mono sound
                            # Duplicate the mono data to create a stereo effect
                            audio_data_stereo = np.stack((original_audio_array, original_audio_array), axis=-1)
                        else:
                            audio_data_stereo = original_audio_array
                        
                        # Adjust volume for each channel according to angle, distance, and config volume
                        audio_data_stereo[:, 0] = (audio_data_stereo[:, 0] * volume_scale_left * distance_factor * FO4Volume_scale).astype(np.int16)  # Left channel
                        audio_data_stereo[:, 1] = (audio_data_stereo[:, 1] * volume_scale_right * distance_factor * FO4Volume_scale).astype(np.int16)  # Right channel
                        
                        # Convert back to pygame sound object
                        adjusted_sound = pygame.sndarray.make_sound(audio_data_stereo)
                        
                        # Play the adjusted stereo audio
                        play_obj = adjusted_sound.play()
                        
                        while play_obj.get_busy():  # Wait until playback is done
                            pygame.time.delay(100)
                        del play_obj
                        self.game_state_manager.write_game_info('_mantella_audio_ready', 'false')
                        break

                    except ValueError:
                        logging.error("Error processing audio array from _mantella_audio_ready.txt")
                        break

    def convert_game_angle_to_trig_angle(self, game_angle):
        #Used for Mantella Fallout to play directional audio
        """
        Convert the game's angle to a trigonometric angle.
        
        Parameters:
        - game_angle: The angle in degrees as used in the game.
        
        Returns:
        - A float representing the angle in degrees, adjusted for standard trigonometry.
        """
        if game_angle < 90:
            return 90 - game_angle
        else:
            return 450 - game_angle

    def calculate_relative_angle(self, player_pos, target_pos, game_angle_z):
         #Used for Mantella Fallout to play directional audio
        """
        Calculate the direction the player is facing relative to the target, taking into account
        the game's unique angle system.
        
        Parameters:
        - player_pos: A tuple (x, y) representing the player's position.
        - target_pos: A tuple (x, y) representing the target's position.
        - game_angle_z: The angle (in degrees) the player is facing, according to the game's system.
        
        Returns:
        - The angle (in degrees) from the player's perspective to the target, where:
            0 = facing towards the target,
            90 = facing left of the target,
            270 = facing right of the target,
            180 = facing away from the target.
        """
        # Convert game angle to trigonometric angle
        trig_angle_z = self.convert_game_angle_to_trig_angle(game_angle_z)
        
        # Calculate vector from player to target
        vector_to_target = (target_pos[0] - player_pos[0], target_pos[1] - player_pos[1])
        
        # Calculate absolute angle of the vector in degrees
        absolute_angle_to_target = math.degrees(math.atan2(vector_to_target[1], vector_to_target[0]))
        
        # Normalize the trigonometric angle
        normalized_trig_angle = trig_angle_z % 360
        
        # Calculate relative angle
        relative_angle = (absolute_angle_to_target - normalized_trig_angle) % 360
        
        # Adjust relative angle to follow the given convention
        if relative_angle > 180:
            relative_angle -= 360  # Adjust for angles greater than 180 to get the shortest rotation direction
        
        return relative_angle

    @utils.time_it
    def remove_files_from_voice_folders(self):
        for sub_folder in os.listdir(self.mod_folder):
            try:
               #if the game is Fallout 4 only delete the lip file
                if self.game =="Fallout4" or self.game =="Fallout4VR": 
                    os.remove(f"{self.mod_folder}/{sub_folder}/{self.f4_lip_file}")
                #delete both the wav file and lip file if the game isn't Fallout4
                else:
                    os.remove(f"{self.mod_folder}/{sub_folder}/{self.wav_file}")
                    os.remove(f"{self.mod_folder}/{sub_folder}/{self.lip_file}")

            except:
                continue


    async def send_audio_to_external_software(self, queue_output):
        logging.info(f"Dialogue to play: {queue_output[0]}")
        self.save_files_to_voice_folders(queue_output)
        
        
        # Remove the played audio file
        #os.remove(audio_file)

        # Remove the played audio file
        #os.remove(audio_file)

    async def send_response(self, sentence_queue, event):
        """Send response from sentence queue generated by `process_response()`"""

        while True:
            queue_output = await sentence_queue.get()
            if queue_output is None:
                logging.info('End of sentences')
                break

            # send the audio file to the external software and wait for it to finish playing
            await self.send_audio_to_external_software(queue_output)
            event.set()

            #if Fallout4 is running the audio will be sync by checking if say line is set to false because the Mantella can internally check if an audio file has finished playing
            if self.game =="Fallout4" or self.game == "Fallout4VR":
                with open(f'{self.root_mod_folder}/_mantella_actor_count.txt', 'r', encoding='utf-8') as f:
                        mantellaactorcount = f.read().strip() 
                # Outer loop to continuously check the files
                while True:
                    all_false = True  # Flag to check if all files have 'false'

                    # Iterate through the number of files indicated by mantellaactorcount
                    for i in range(1, int(mantellaactorcount) + 1):
                        file_name = f'{self.root_mod_folder}/_mantella_say_line'
                        if i != 1:
                            file_name += f'_{i}'  # Append the file number for files 2 and above
                        file_name += '.txt'

                        with open(file_name, 'r', encoding='utf-8') as f:
                            content = f.read().strip()
                            if content.lower() != 'false':
                                all_false = False  # Set the flag to False if any file is not 'false'
                                break  # Break the for loop and continue the while loop

                    if all_false:
                        break  # Break the outer loop if all files are 'false'

                    # Wait for a short period before checking the files again
                    await asyncio.sleep(0.1)  # Adjust the sleep duration as needed

            #if Skyrim's running then estimate audio duration to sync lip files
            else:
                audio_duration = await self.get_audio_duration(queue_output[0])
                # wait for the audio playback to complete before getting the next file
                logging.info(f"Waiting {int(round(audio_duration,4))} seconds...")
                await asyncio.sleep(audio_duration)

    def clean_sentence(self, sentence):
        def remove_as_a(sentence):
            """Remove 'As an XYZ,' from beginning of sentence"""
            if sentence.startswith('As a'):
                if ', ' in sentence:
                    logging.info(f"Removed '{sentence.split(', ')[0]} from response")
                    sentence = sentence.replace(sentence.split(', ')[0]+', ', '')
            return sentence
        
        def parse_asterisks_brackets(sentence):
            if ('*' in sentence):
                # Check if sentence contains two asterisks
                asterisk_check = re.search(r"(?<!\*)\*(?!\*)[^*]*\*(?!\*)", sentence)
                if asterisk_check:
                    logging.info(f"Removed asterisks text from response: {sentence}")
                    # Remove text between two asterisks
                    sentence = re.sub(r"(?<!\*)\*(?!\*)[^*]*\*(?!\*)", "", sentence)
                else:
                    logging.info(f"Removed response containing single asterisks: {sentence}")
                    sentence = ''

            if ('(' in sentence) or (')' in sentence):
                # Check if sentence contains two brackets
                bracket_check = re.search(r"\(.*\)", sentence)
                if bracket_check:
                    logging.info(f"Removed brackets text from response: {sentence}")
                    # Remove text between brackets
                    sentence = re.sub(r"\(.*?\)", "", sentence)
                else:
                    logging.info(f"Removed response containing single bracket: {sentence}")
                    sentence = ''

            return sentence
        
        if ('Well, well, well' in sentence):
            sentence = sentence.replace('Well, well, well', 'Well well well')

        sentence = remove_as_a(sentence)
        sentence = sentence.replace('"','')
        sentence = sentence.replace('[', '(')
        sentence = sentence.replace(']', ')')
        sentence = sentence.replace('{', '(')
        sentence = sentence.replace('}', ')')
        # local models sometimes get the idea in their head to use double asterisks **like this** in sentences instead of single
        # this converts double asterisks to single so that they can be filtered out appropriately
        sentence = sentence.replace('**','*')
        sentence = parse_asterisks_brackets(sentence)
        return sentence


    async def process_response(self, sentence_queue, input_text, messages, synthesizer, characters, radiant_dialogue, event):
        """Stream response from LLM one sentence at a time"""

        messages.append({"role": "user", "content": input_text})
        sentence = ''
        full_reply = ''
        num_sentences = 0
        action_taken = False
        if self.alternative_openai_api_base == 'none':
            openai.aiosession.set(ClientSession()) # https://github.com/openai/openai-python#async-api
        while True:
            try:
                start_time = time.time()
                async for chunk in await openai.ChatCompletion.acreate(model=self.llm, messages=messages, headers={"HTTP-Referer": 'https://github.com/art-from-the-machine/Mantella', "X-Title": 'mantella'}, stream=True, stop=self.stop, temperature=self.temperature, top_p=self.top_p, frequency_penalty=self.frequency_penalty, max_tokens=self.max_tokens):
                    content = chunk["choices"][0].get("delta", {}).get("content")

                    if content is not None:
                        sentence += content
                        # Check for the last occurrence of sentence-ending punctuation
                        last_punctuation = max(sentence.rfind('.'), sentence.rfind('!'), sentence.rfind(':'), sentence.rfind('?'))
                        if last_punctuation != -1:
                            # Split the sentence at the last punctuation mark
                            remaining_content = sentence[last_punctuation + 1:]
                            sentence = sentence[:last_punctuation + 1]

                        #Don't ban the word assist for Fallout because they're are too many NPC characters that are portraying some kind of AI/robot so most LLMs will tend to use that word.
                        if self.game !="Fallout4" and self.game != "Fallout4VR":
                            if ('assist' in content) and (num_sentences>0):
                                logging.info(f"'assist' keyword found. Ignoring sentence which begins with: {sentence}")
                                break

                        content_edit = unicodedata.normalize('NFKC', content)
                        # check if content marks the end of a sentence
                        if (any(char in content_edit for char in self.end_of_sentence_chars)):
                            sentence = self.clean_sentence(sentence)

                            if len(sentence.strip()) < 3:
                                logging.info(f'Skipping voiceline that is too short: {sentence}')
                                break

                            logging.info(f"LLM returned sentence took {time.time() - start_time} seconds to execute")

                            if content_edit == ':':
                                keyword_extraction = sentence.strip()[:-1] #.lower()
                                # if LLM is switching character
                                if (keyword_extraction in characters.active_characters):
                                    #TODO: or (any(key.split(' ')[0] == keyword_extraction for key in characters.active_characters))
                                    logging.info(f"Switched to {keyword_extraction}")
                                    self.active_character = characters.active_characters[keyword_extraction]
                                    synthesizer.change_voice(self.active_character.voice_model)
                                    # characters are mapped to say_line based on order of selection
                                    # taking the order of the dictionary to find which say_line to use, but it is bad practice to use dictionaries in this way
                                    self.character_num = list(characters.active_characters.keys()).index(keyword_extraction)
                                    full_reply += sentence
                                    sentence = ''
                                    action_taken = True
                                elif keyword_extraction == 'Player':
                                    logging.info(f"Stopped LLM from speaking on behalf of the player")
                                    break
                                elif keyword_extraction.lower() == self.offended_npc_response.lower():
                                    logging.info(f"The player offended the NPC")
                                    self.game_state_manager.write_game_info('_mantella_aggro', '1')
                                    self.active_character.is_in_combat = 1
                                    full_reply += sentence
                                    sentence = ''
                                    action_taken = True
                                elif keyword_extraction.lower() == self.forgiven_npc_response.lower():
                                    logging.info(f"The player made up with the NPC")
                                    self.game_state_manager.write_game_info('_mantella_aggro', '0')
                                    self.active_character.is_in_combat = 0
                                    full_reply += sentence
                                    sentence = ''
                                    action_taken = True
                                elif keyword_extraction.lower() == self.follow_npc_response.lower():
                                    logging.info(f"The NPC is willing to follow the player")
                                    self.game_state_manager.write_game_info('_mantella_aggro', '2')
                                    full_reply += sentence
                                    sentence = ''
                                    action_taken = True

                            if action_taken == False:
                                # Generate the audio and return the audio file path
                                try:
                                    audio_file = synthesizer.synthesize(self.active_character.voice_model, None, ' ' + sentence + ' ', self.active_character.is_in_combat)
                                except Exception as e:
                                    logging.error(f"xVASynth Error: {e}")

                                # Put the audio file path in the sentence_queue
                                await sentence_queue.put([audio_file, sentence])

                                full_reply += sentence
                                num_sentences += 1
                                sentence = ''
                                sentence = remaining_content
                                remaining_content = ''

                                # clear the event for the next iteration
                                event.clear()
                                # wait for the event to be set before generating the next line
                                await event.wait()

                                end_conversation = self.game_state_manager.load_data_when_available('_mantella_end_conversation', '')
                                radiant_dialogue_update = self.game_state_manager.load_data_when_available('_mantella_radiant_dialogue', '')
                                # stop processing LLM response if:
                                # max_response_sentences reached (and the conversation isn't radiant)
                                # conversation has switched from radiant to multi NPC (this allows the player to "interrupt" radiant dialogue and include themselves in the conversation)
                                # the conversation has ended
                                if ((num_sentences >= self.max_response_sentences) and (radiant_dialogue == 'false')) or ((radiant_dialogue == 'true') and (radiant_dialogue_update.lower() == 'false')) or (end_conversation.lower() == 'true'):
                                    break
                            else:
                                action_taken = False
                if self.alternative_openai_api_base == 'none':
                    await openai.aiosession.get().close()
                break
            except Exception as e:
                logging.error(f"LLM API Error: {e}")
                error_response = "I can't find the right words at the moment."
                audio_file = synthesizer.synthesize(self.active_character.voice_model, None, error_response)
                self.save_files_to_voice_folders([audio_file, error_response])
                logging.info('Retrying connection to API...')
                time.sleep(5)

        # Mark the end of the response
        await sentence_queue.put(None)

        messages.append({"role": "assistant", "content": full_reply})
        logging.info(f"Full response saved ({len(self.encoding.encode(full_reply))} tokens): {full_reply}")

        return messages
