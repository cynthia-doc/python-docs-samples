# Copyright 2021 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import logging
import random
from typing import List

import apache_beam as beam
from apache_beam.options.pipeline_options import PipelineOptions
import pandas as pd
import tensorflow as tf

import data_utils
import trainer


def run(
    raw_data_dir: str,
    raw_labels_dir: str,
    train_data_dir: str,
    eval_data_dir: str,
    train_eval_split: List[int],
    **beam_args: List[str],
) -> str:

    labels = pd.concat(
        [
            data_utils.read_labels(filename)
            for filename in tf.io.gfile.glob(f"{raw_labels_dir}/*.csv")
        ]
    ).sort_values(by="start_time")

    beam_options = PipelineOptions(
        flags=[],
        save_main_session=True,
        requirements_file="requirements.txt",
        **beam_args,
    )
    pipeline = beam.Pipeline(options=beam_options)

    training_data, evaluation_data = (
        pipeline
        | "Data files" >> beam.Create([f"{raw_data_dir}/*.npz"])
        | "Expand pattern" >> beam.FlatMap(tf.io.gfile.glob)
        | "Reshuffle files" >> beam.Reshuffle()
        | "Read data" >> beam.Map(data_utils.read_data)
        | "Label data" >> beam.Map(data_utils.label_data, labels)
        | "Get training points" >> beam.FlatMap(data_utils.generate_training_points)
        | "Serialize TFRecords" >> beam.Map(trainer.serialize)
        | "Train-eval split"
        >> beam.Partition(lambda x, n: random.choices([0, 1], train_eval_split)[0], 2)
    )

    (
        training_data
        | "Write train files"
        >> beam.io.WriteToTFRecord(
            f"{train_data_dir}/part",
            file_name_suffix=".tfrecords.gz",
            compression_type=beam.io.filesystems.CompressionTypes.GZIP,
        )
    )

    (
        evaluation_data
        | "Write eval files"
        >> beam.io.WriteToTFRecord(
            f"{eval_data_dir}/part",
            file_name_suffix=".tfrecords.gz",
            compression_type=beam.io.filesystems.CompressionTypes.GZIP,
        )
    )

    result = pipeline.run()
    logging.info(result)
    try:
        return result._job.id
    except Exception:
        return beam_args.get("job_name")
