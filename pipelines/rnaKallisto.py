#!/usr/bin/env python

"""
QUANT-seq pipeline
"""

import sys
from argparse import ArgumentParser
import yaml
import pypiper
import os

try:
	from pipelines.models import AttributeDict
	from pipelines import toolkit as tk
except:
	sys.path.append(os.path.join(os.path.dirname(__file__), "pipelines"))
	from models import AttributeDict
	import toolkit as tk


__author__ = "Andre Rendeiro"
__copyright__ = "Copyright 2015, Andre Rendeiro"
__credits__ = []
__license__ = "GPL2"
__version__ = "0.2"
__maintainer__ = "Andre Rendeiro"
__email__ = "arendeiro@cemm.oeaw.ac.at"
__status__ = "Development"


def main():
	# Parse command-line arguments
	parser = ArgumentParser(
		prog="rnaKallisto",
		description="Kallisto pipeline."
	)
	parser = arg_parser(parser)
	parser = pypiper.add_pypiper_args(parser, args=["True"])
	args = parser.parse_args()

	# Read in yaml configs
	sample = AttributeDict(yaml.load(open(args.sample_config, "r")))
	pipeline_config = AttributeDict(yaml.load(open(os.path.join(os.path.dirname(__file__), args.config_file), "r")))

	# Start main function
	process(sample, pipeline_config, args)


def arg_parser(parser):
	"""
	Global options for pipeline.
	"""
	parser.add_argument(
		"-y", "--sample-yaml",
		dest="sample_config",
		help="Yaml config file with sample attributes.",
		type=str
	)
	parser.add_argument(
		"-qs","--quantseq",
		dest="quantseq",
		action="store_true",
		default=False,
		help="Enables quantseq specific options"
	)
	return parser


def process(sample, pipeline_config, args):
	"""
	This takes unmapped Bam files and makes trimmed, aligned, duplicate marked
	and removed, indexed, shifted Bam files along with a UCSC browser track.
	Peaks are called and filtered.
	"""

	print("Start processing sample %s." % sample.sample_name)

	for path in ["sample_root"] + sample.paths.__dict__.keys():
		if not os.path.exists(sample.paths[path]):
			try:
				os.mkdir(sample.paths[path])
			except OSError("Cannot create '%s' path: %s" % (path, sample.paths[path])):
				raise

	# Start Pypiper object
	pm = pypiper.PipelineManager("rnaKallisto", sample.paths.sample_root, args=args)

	print "\nPipeline configuration:"
	print(pm.config)
	tools = pm.config.tools  # Convenience alias
	param = pm.config.parameters
	resources = pm.config.resources

	sample.paired = False
	if args.single_or_paired == "paired": sample.paired = True

	# Create a ngstk object
	myngstk = pypiper.NGSTk(pm=pm)

	# Merge Bam files if more than one technical replicate
	if len(sample.data_path.split(" ")) > 1:
		pm.timestamp("Merging bam files from replicates")
		cmd = tk.mergeBams(
			inputBams=sample.data_path.split(" "),  # this is a list of sample paths
			outputBam=sample.unmapped
		)
		pm.run(cmd, sample.unmapped, shell=True)
		sample.data_path = sample.unmapped

	# Convert bam to fastq
	pm.timestamp("Converting to Fastq format")

	param.pipeline_outfolder = os.path.abspath(os.path.join(args.output_parent, args.sample_name))
	cmd, fastq_folder, out_fastq_pre, unaligned_fastq = myngstk.input_to_fastq(sample.data_path, param.pipeline_outfolder, args.sample_name, sample.paired)
	myngstk.make_sure_path_exists(fastq_folder)
	pm.run(cmd, unaligned_fastq, follow=myngstk.check_fastq(sample.data_path, unaligned_fastq, sample.paired))

	sample.fastq = out_fastq_pre + "_R1.fastq "
	sample.trimmed = out_fastq_pre + "_R1_trimmed.fq "
	sample.fastq1 = out_fastq_pre + "_R1.fastq " if sample.paired else None
	sample.fastq2 = out_fastq_pre + "_R2.fastq " if sample.paired else None
	sample.trimmed1 = out_fastq_pre + "_R1_trimmed.fq " if sample.paired else None
	sample.trimmed1Unpaired = out_fastq_pre + "_R1_unpaired.fq " if sample.paired else None
	sample.trimmed2 = out_fastq_pre + "_R2_trimmed.fq " if sample.paired else None
	sample.trimmed2Unpaired + "_R2_unpaired.fq " if sample.paired else None

	#if not sample.paired:
	#	pm.clean_add(sample.fastq, conditional=True)
	#if sample.paired:
	#	pm.clean_add(sample.fastq1, conditional=True)
	#	pm.clean_add(sample.fastq2, conditional=True)
	#	pm.clean_add(sample.fastqUnpaired, conditional=True)

	# Trim reads
	pm.timestamp("Trimming adapters from sample")
	if pipeline_config.parameters.trimmer == "trimmomatic":

		inputFastq1 = sample.fastq1 if sample.paired else sample.fastq
		inputFastq2 = sample.fastq2 if sample.paired else None
		outputFastq1 = sample.trimmed1 if sample.paired else sample.trimmed
		outputFastq1unpaired = sample.trimmed1Unpaired if sample.paired else None
		outputFastq2 = sample.trimmed2 if sample.paired else None
		outputFastq2unpaired = sample.trimmed2Unpaired if sample.paired else None

		PE = sample.paired
		pe = "PE" if PE else "SE"
		cmd = tools.java + " -Xmx" + str(pm.mem) + " -jar " + tools.trimmomatic
		cmd += " {0} -threads {1} {2}".format(pe, args.cores, inputFastq1)
		if PE:
			cmd += " {0}".format(inputFastq2)
		cmd += " {0}".format(outputFastq1)
		if PE:
			cmd += " {0} {1} {2}".format(outputFastq1unpaired, outputFastq2, outputFastq2unpaired)
		if args.quantseq: cmd += " HEADCROP:6"
		cmd += " ILLUMINACLIP:" + resources.adapters + ":2:10:4:1:true"
		if args.quantseq: cmd += " ILLUMINACLIP:" + "/data/groups/lab_bsf/resources/trimmomatic_adapters/PolyA-SE.fa" + ":2:30:5:1:true"
		cmd += " SLIDINGWINDOW:4:1"
		cmd += " MAXINFO:16:0.40"
		cmd += " MINLEN:21"


		pm.run(cmd, sample.trimmed1 if sample.paired else sample.trimmed, shell=True, nofail=True)
		if not sample.paired:
			pm.clean_add(sample.trimmed, conditional=True)
		else:
			pm.clean_add(sample.trimmed1, conditional=True)
			pm.clean_add(sample.trimmed1Unpaired, conditional=True)
			pm.clean_add(sample.trimmed2, conditional=True)
			pm.clean_add(sample.trimmed2Unpaired, conditional=True)

	elif pipeline_config.parameters.trimmer == "skewer":
		cmd = tk.skewer(
			inputFastq1=sample.fastq1 if sample.paired else sample.fastq,
			inputFastq2=sample.fastq2 if sample.paired else None,
			outputPrefix=os.path.join(sample.paths.unmapped, sample.sample_name),
			outputFastq1=sample.trimmed1 if sample.paired else sample.trimmed,
			outputFastq2=sample.trimmed2 if sample.paired else None,
			trimLog=sample.trimlog,
			cpus=args.cores,
			adapters=pipeline_config.resources.adapters
		)
		pm.run(cmd, sample.trimmed1 if sample.paired else sample.trimmed, shell=True, nofail=True)
		if not sample.paired:
			pm.clean_add(sample.trimmed, conditional=True)
		else:
			pm.clean_add(sample.trimmed1, conditional=True)
			pm.clean_add(sample.trimmed2, conditional=True)

	# With kallisto from unmapped reads
	pm.timestamp("Quantifying read counts with kallisto")

	inputFastq = sample.trimmed1 if sample.paired else sample.trimmed
	inputFastq2 = sample.trimmed1 if sample.paired else None
	transcriptomeIndex = resources.genome_index[sample.transcriptome]

	bval = 0 # Number of bootstrap samples (default: 0)
	size = 50 # Estimated average fragment length
	sdev = 20 # Estimated standard deviation of fragment length
	cmd1 = tools.kallisto + " quant -b {0} -l {1} -s {2} -i {3} -o {4} -t {5}".format(bval, size, sdev, transcriptomeIndex, sample.paths.quant, args.cores)
	if not sample.paired:
		cmd1 += " --single {0}".format(inputFastq)
	else:
		cmd1 += " {0} {1}".format(inputFastq, inputFastq2)
	cmd2 = tools.kallisto + " h5dump -o {0} {0}/abundance.h5".format(sample.paths.quant)

	pm.run([cmd1,cmd2], sample.kallistoQuant, shell=True, nofail=True)

	pm.stop_pipeline()
	print("Finished processing sample %s." % sample.sample_name)


if __name__ == '__main__':
	try:
		sys.exit(main())
	except KeyboardInterrupt:
		print("Program canceled by user!")
		sys.exit(1)
