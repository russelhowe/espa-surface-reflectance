#!/usr/bin/env python

############################################################################
# Original development on 9/2/2014 by Gail Schmidt, USGS EROS
# Updated on 9/9/2015 by Gail Schmidt, USGS EROS
#   Modified the wget calls to retry up to 5 times if the download fails.
############################################################################
import sys
import os
import fnmatch
import ftplib
import datetime
import commands
import re
import time
import subprocess
from optparse import OptionParser
import requests
import logging

# Global static variables
ERROR = 1
SUCCESS = 0
START_YEAR = 2013      # quarterly processing will reprocess back to the
                       # start year to make sure all data is up to date
                       # Landsat 8 was launched on Feb. 11, 2013

############################################################################
# DatasourceResolver class
############################################################################
class DatasourceResolver:
    # Specify the base location for the LAADS data as well as the
    # correct subdirectories for each of the instrument-specific ozone
    # products
    # These are version 006 products
    SERVER_URL_CMA = 'ladssci.nascom.nasa.gov'
    SERVER_URL_CMG = 'ladsweb.nascom.nasa.gov'
    TERRA_CMA = '/6/MOD09CMA/'
    TERRA_CMG = '/allData/6/MOD09CMG/'
    AQUA_CMA =  '/6/MYD09CMA/'
    AQUA_CMG =  '/allData/6/MYD09CMG/'

    user = None
    password = None

    def __init__(self):
        if(self.user is None or self.password is None):
            (self.user, self.password) = get_credentials_from_production()

        logger = logging.getLogger(__name__)  # Obtain logger for this module.
        logger.info('LADSFTP username: {0}'.format(self.user))
        logger.info('LADSFTP password: {0}'.format(self.password))


    #######################################################################
    # Description: buildURL builds the URLs for the Terra and Aqua CMG and
    # CMA products for the current year and DOY, and put that URL on the list.
    #
    # Inputs:
    #   year - year of desired LAADS data
    #   DOY - day of year of desired LAADS data
    #
    # Returns:
    #   None - error resolving the instrument and associated URL for the
    #          specified year and DOY
    #   urlList - List of URLs to pull the LAADS data from for the specified
    #             year and DOY.
    #
    # Notes:
    #######################################################################
    def buildURLs(self, year, doy):
        urlList = []     # create empty URL list

        # append TERRA CMA data
        url = 'ftp://%s:%s@%s%s%d/%03d/MOD09CMA*%d%03d*.hdf' % \
            (self.user, self.password, self.SERVER_URL_CMA, self.TERRA_CMA, year,
             doy, year, doy)
        urlList.append(url)

        # append TERRA CMG data
        url = 'ftp://%s%s%d/%03d/MOD09CMG*%d%03d*.hdf' % \
            (self.SERVER_URL_CMG, self.TERRA_CMG, year,
             doy, year, doy)
        urlList.append(url)

        # append AQUA CMA data
        url = 'ftp://%s:%s@%s%s%d/%03d/MYD09CMA*%d%03d*.hdf' % \
            (self.user, self.password, self.SERVER_URL_CMA, self.AQUA_CMA, year,
             doy, year, doy)
        urlList.append(url)

        # append AQUA CMG data
        url = 'ftp://%s%s%d/%03d/MYD09CMG*%d%03d*.hdf' % \
            (self.SERVER_URL_CMG, self.AQUA_CMG, year,
             doy, year, doy)
        urlList.append(url)

        return urlList

############################################################################
# End DatasourceResolver class
############################################################################


#######################################################################
# Description: Obtains ftp credentials (username and password) from
# production service.
#
# Precondition:
#   Requires environmental variable, ESPA_LAADS_CONFIG, to be set equal to the
#       http address of the service.
#   Assumes ESPA_LAADS_CONFIG http link is accessable from local system.
#
# Postcondition:
#   Returns tuple containing (username, password)
#   Returns None if error occured
#       Occurs if service could not be reached
#       Occurs if empty credentials were recieved from the service
#
#######################################################################
def get_credentials_from_production():
    # get the logger
    logger = logging.getLogger(__name__)

    # determine the auxiliary directory to store the data
    laads_config = os.environ.get('ESPA_LAADS_CONFIG')
    if laads_config is None:
        msg = "ESPA_LAADS_CONFIG environment variable not set... exiting"
        logger.error(msg)
        return None

    # get the LAADS username and password
    # username
    username_url = '{0}/ladsftp.username'.format(laads_config)
    response = requests.get(username_url)
    if not response.ok:
        msg = 'Error fetching LAADS credentials'
        logger.error(msg)
        return None
    user = response.json()['ladsftp.username']
    logger.debug('username: {0}'.format(user))

    # password
    pwd_url = '{0}/ladsftp.password'.format(laads_config)
    response = requests.get(pwd_url)
    if not response.ok:
        msg = 'Error fetching LAADS credentials'
        logger.error(msg)
        return None
    password = response.json()['ladsftp.password']
    logger.debug('password: {0}'.format(password))

    # verify that the ESPA_LAADS_CONFIG service returned valid information and
    # the username and password were set in the configuration
    if len(user) <= 0 or len(password) <= 0:
        msg = "Received invalid sized credentials for LAADS FTP from " \
            "ESPA_LAADS_CONFIG service. Make sure ladsftp.username and " \
            "ladsftp.password are set in the ESPA_LAADS_CONFIG."
        logger.error(msg)
        return None

    return (user, password)


############################################################################
# Description: isLeapYear will determine if the specified year is a leap
# year.
#
# Inputs:
#   year - year to determine if it is a leap year (integer)
#
# Returns:
#     True - yes, this is a leap year
#     False - no, this is not a leap year
#
# Notes:
############################################################################
def isLeapYear (year):
    if (year % 4) == 0:
        if (year % 100) == 0:
            if (year % 400) == 0:
                return True
            else:
                return False
        else:
            return True
    else:
        return False


############################################################################
# Description: downloadLads will retrieve the files for the specified year
# and DOY from the LAADS ftp site and download to the desired destination.
# If the destination directory does not exist, then it is made before
# downloading.  Existing files in the download directory are removed/cleaned.
# This will download the Aqua/Terra CMG and CMA files for the current year, DOY.
#
# Inputs:
#   year - year of data to download (integer)
#   doy - day of year of data to download (integer)
#   destination - name of the directory on the local system to download the
#                 LAADS files
#
# Returns:
#     ERROR - error occurred while processing
#     SUCCESS - processing completed successfully
#
# Notes:
#   We could use the Python ftplib or urllib modules, however the wget
#   function is pretty short and sweet, so we'll stick with wget.
############################################################################
def downloadLads (year, doy, destination):
    # get the logger
    logger = logging.getLogger(__name__)

    # make sure the download directory exists (and is cleaned up) or create
    # it recursively
    if not os.path.exists(destination):
        msg = "%s does not exist... creating" % destination
        logger.info(msg)
        os.makedirs(destination, 0777)
    else:
        # directory already exists and possibly has files in it.  any old
        # files need to be cleaned up
        msg = "Cleaning download directory: %s" % destination
        logger.info(msg)
        for myfile in os.listdir(destination):
            name = os.path.join(destination, myfile)
            if not os.path.isdir(name):
                os.remove(name)

    # obtain the list of URL(s) for our particular date.  this includes the
    # locations for the Aqua and Terra CMG/CMA files.
    urlList = DatasourceResolver().buildURLs(year, doy)
    if urlList is None:
        msg = "LAADS URLs could not be resolved for year %d and DOY %d." % \
            (year, doy)
        logger.error(msg)
        return ERROR

    # download the data for the current year from the list of URLs.
    # if there is a problem with the connection, then retry up to 5 times.
    # Note: if you don't like the wget output, --quiet can be used to minimize
    # the output info.
    msg = "Downloading data for year %d to: %s" % (year, destination)
    logger.info(msg)
    for url in urlList:
        msg = "Retrieving %s to %s" % (url, destination)
        logger.info(msg)
        cmd = 'wget --tries=5 %s' % url
        retval = subprocess.call(cmd, shell=True, cwd=destination)

        # make sure the wget was successful or retry up to 5 more times and
        # sleep in between
        if retval:
            retry_count = 1
            while ((retry_count <= 5) and (retval)):
                time.sleep(60)
                logger.info('Retry {0} of wget for {1}'
                            .format(retry_count, url))
                retval = subprocess.call(cmd, shell=True, cwd=destination)
                retry_count += 1

            if retval:
                logger.warn('Unsuccessful download of {0} (retried 5 times)'
                            .format(url))

    return SUCCESS


############################################################################
# Description: getLadsData downloads the daily MODIS Aqua/Terra CMG and CMA
# data files for the desired year, then combines those files into one daily
# product containing the various ozone, water vapor, temperature, etc. SDSs.
#
# Inputs:
#   auxdir - name of the base L8_SR auxiliary directory which contains
#            the LAADS directory
#   year - year of LAADS data to be downloaded and processed (integer)
#   today - specifies if we are just bringing the LAADS data up to date vs.
#           reprocessing the data
#
# Returns:
#     ERROR - error occurred while processing
#     SUCCESS - processing completed successfully
#
# Notes:
############################################################################
def getLadsData (auxdir, year, today):
    # get the logger
    logger = logging.getLogger(__name__)

    # determine the directory for the output auxiliary data files to be
    # processed.  create the directory if it doesn't exist.
    outputDir = "%s/LADS/%d" % (auxdir, year)
    if not os.path.exists(outputDir):
        msg = "%s does not exist... creating" % outputDir
        logger.info(msg)
        os.makedirs(outputDir, 0777)

    # if the specified year is the current year, only process up through
    # today (actually 2 days earlier due to the LAADS data lag) otherwise
    # process through all the days in the year
    now = datetime.datetime.now()
    if year == now.year:
        # start processing LAADS data with a 2-day time lag. if the 2-day lag
        # puts us into last year, then we are done with the current year.
        day_of_year = now.timetuple().tm_yday - 2
        if day_of_year <= 0:
            return SUCCESS
    else:
        if isLeapYear (year) == True:
            day_of_year = 366   
        else:
            day_of_year = 365

    # set the download directory in /tmp/lads
    dloaddir = "/tmp/lads/%d" % year

    # loop through each day in the year and process the LAADS data.  process
    # in the reverse order so that if we are handling data for "today", then
    # we can stop as soon as we find the current DOY has been processed.
    for doy in range(day_of_year, 0, -1):
        # get the year + DOY string
        datestr = "%d%03d" % (year, doy)

        # if the data for the current year and doy exists already, then we are
        # going to skip that file if processing for the --today.  For
        # --quarterly, we will completely reprocess.
        skip_date = False
        for myfile in os.listdir(outputDir):
            if fnmatch.fnmatch (myfile, 'L8ANC' + datestr + '.hdf_fused') \
                and today:
                msg = 'L8ANC' + datestr + '.hdf_fused already exists. Skip.'
                logger.info(msg)
                skip_date = True
                break

        if skip_date:
            continue

        # download the daily LAADS files for the specified year and DOY
        status = downloadLads (year, doy, dloaddir)
        if status == ERROR:
            # warning message already printed
            return ERROR

        # get the Terra CMA file for the current DOY (should only be one)
        fileList = []    # create empty list to store files matching date
        for myfile in os.listdir(dloaddir):
            if fnmatch.fnmatch (myfile, 'MOD09CMA.A' + datestr + '*.hdf'):
                fileList.append (myfile)

        # make sure files were found or print a warning
        nfiles = len(fileList)
        if nfiles == 0:
            msg = "No LAADS MOD09CMA data available for doy %d year %d." % \
                (doy, year)
            logger.warning(msg)
            continue
        else:
            # if only one file was found which matched our date, then that's
            # the file we'll process.  if more than one was found, then we
            # have a problem as only one file is expected.
            if nfiles == 1:
                terra_cma = dloaddir + '/' + fileList[0]
            else:
                msg = "Multiple LAADS MOD09CMA files found for doy %d year " \
                    "%d." % (doy, year)
                logger.error(msg)
                return ERROR

        # get the Terra CMG file for the current DOY (should only be one)
        fileList = []    # create empty list to store files matching date
        for myfile in os.listdir(dloaddir):
            if fnmatch.fnmatch (myfile, 'MOD09CMG.A' + datestr + '*.hdf'):
                fileList.append(myfile)

        # make sure files were found or print a warning
        nfiles = len(fileList)
        if nfiles == 0:
            msg = "No LAADS MOD09CMG data available for doy %d year %d." % \
                (doy, year)
            logger.warning(msg)
            continue
        else:
            # if only one file was found which matched our date, then that's
            # the file we'll process.  if more than one was found, then we
            # have a problem as only one file is expected.
            if nfiles == 1:
                terra_cmg = dloaddir + '/' + fileList[0]
            else:
                msg = "Multiple LAADS MOD09CMG files found for doy %d year " \
                    "%d." % (doy, year)
                logger.error(msg)
                return ERROR

        # get the Aqua CMA file for the current DOY (should only be one)
        fileList = []    # create empty list to store files matching date
        for myfile in os.listdir(dloaddir):
            if fnmatch.fnmatch (myfile, 'MYD09CMA.A' + datestr + '*.hdf'):
                fileList.append(myfile)

        # make sure files were found or print a warning
        nfiles = len(fileList)
        if nfiles == 0:
            msg = "No LAADS MYD09CMA data available for doy %d year %d." % \
                (doy, year)
            logger.warning(msg)
            continue
        else:
            # if only one file was found which matched our date, then that's
            # the file we'll process.  if more than one was found, then we
            # have a problem as only one file is expected.
            if nfiles == 1:
                aqua_cma = dloaddir + '/' + fileList[0]
            else:
                msg = "Multiple LAADS MYD09CMA files found for doy %d year " \
                    "%d." % (doy, year)
                logger.error(msg)
                return ERROR

        # get the Aqua CMG file for the current DOY (should only be one)
        fileList = []    # create empty list to store files matching date
        for myfile in os.listdir(dloaddir):
            if fnmatch.fnmatch (myfile, 'MYD09CMG.A' + datestr + '*.hdf'):
                fileList.append(myfile)

        # make sure files were found or print a warning
        nfiles = len(fileList)
        if nfiles == 0:
            msg = "No LAADS MYD09CMG data available for doy %d year %d." % \
                (doy, year)
            logger.warning(msg)
            continue
        else:
            # if only one file was found which matched our date, then that's
            # the file we'll process.  if more than one was found, then we
            # have a problem as only one file is expected.
            if nfiles == 1:
                aqua_cmg = dloaddir + '/' + fileList[0]
            else:
                msg = "Multiple LAADS MYD09CMG files found for doy %d year " \
                    "%d." % (doy, year)
                logger.error(msg)
                return ERROR

        # generate the full path for the input and output file to be
        # processed. if the output file already exists, then remove it.
        cmdstr = 'combine_l8_aux_data --terra_cmg %s --terra_cma %s ' \
            '--aqua_cmg %s --aqua_cma %s --output_dir %s' % (terra_cmg, \
            terra_cma, aqua_cmg, aqua_cma, outputDir)
        msg = "Executing %s\n" % cmdstr
        logger.info(msg)

        (status, output) = commands.getstatusoutput (cmdstr)
        logger.info(output)
        exit_code = status >> 8
        if exit_code != 0:
            msg = "Error running combine_l8_aux_data for year %d, DOY %d." % \
                (year, doy)
            logger.error(msg)
            return ERROR
    # end for doy

    # remove the files downloaded to the temporary directory
    msg = "Removing downloaded files from %s" % dloaddir
    logger.info(msg)
    if os.path.exists(dloaddir):
        for myfile in os.listdir(dloaddir):
            name = os.path.join(dloaddir, myfile)
            os.remove(name)

    return SUCCESS


############################################################################
# Description: Main routine which grabs the command-line arguments, determines
# which years/days of data need to be processed, then processes the user-
# specified dates of LAADS data.
#
# Developer(s):
#     Gail Schmidt, USGS EROS - Original development
#
# Returns:
#     ERROR - error occurred while processing
#     SUCCESS - processing completed successfully
#
# Notes:
# 1. This script can be called with the --today option or with a combination
#    of --start_year / --end_year.  --today trumps --quarterly and
#    --start_year / --end_year.
# 2. --today will process the data for the most recent year (including the
#    previous year if the DOY is within the first month of the year).  Thus
#    this option is used for nightly updates.  If the hdf fused data products
#    already exist for a particular year/doy, they will not be reprocessed.
# 3. --quarterly will process the data for today all the way back to the
#    earliest year so that any updated LAADS files are picked up and
#    processed.  Thus this option is used for quarterly updates.
# 4. Existing LAADS HDF files are removed before processing data for that
#    year and DOY, but only if the downloaded auxiliary data exists for that
#    date.
############################################################################
def main ():
    logger = logging.getLogger(__name__)  # Get logger for the module.

    # get the command line arguments
    parser = OptionParser()
    parser.add_option ('-s', '--start_year', type='int', dest='syear',
        default=0, help='year for which to start pulling LAADS data')
    parser.add_option ('-e', '--end_year', type='int', dest='eyear',
        default=0, help='last year for which to pull LAADS data')
    parser.add_option('-u', '--username', dest='username', type='string',
                      help='username to use for LAADS ftp site '
                           '(ladssci.nascom.nasa.gov)')
    parser.add_option('-p', '--password', dest='password', type='string',
                      help='password to use for LAADS ftp site '
                           '(ladssci.nascom.nasa.gov)')
    parser.add_option ('--today', dest='today', default=False,
        action='store_true',
        help='process LAADS data up through the most recent year and DOY')
    msg = 'process or reprocess all LAADS data from today back to %d' %  \
        START_YEAR
    parser.add_option ('--quarterly', dest='quarterly', default=False,
        action='store_true', help=msg)

    (options, args) = parser.parse_args()
    syear = options.syear           # starting year
    eyear = options.eyear           # ending year
    today = options.today           # process most recent year of data
    quarterly = options.quarterly   # process today back to START_YEAR

    if((options.username is None) and (options.password is None)):
        logger.info('Credentials obtained from ESPA_LAADS_CONFIG service will '
                    'be used')
    elif((options.username is not None) and (options.password is not None)):
        DatasourceResolver.user = options.username
        DatasourceResolver.password = options.password
    else:
        raise Exception('It is invalid to specify --username or --password'
                        ' argument without the other.')

    # check the arguments
    if (today == False) and (quarterly == False) and \
       (syear == 0 or eyear == 0):
        msg = "Invalid command line argument combination.  Type --help "  \
            "for more information"
        logger.error(msg)
        return ERROR

    # determine the auxiliary directory to store the data
    auxdir = os.environ.get('L8_AUX_DIR')
    if auxdir is None:
        msg = "L8_AUX_DIR environment variable not set... exiting"
        logger.error(msg)
        return ERROR

    # if processing today then process the current year.  if the current
    # DOY is within the first month, then process the previous year as well
    # to make sure we have all the recently available data processed.
    if today:
        msg = "Processing LAADS data up to the most recent year and DOY."
        logger.info(msg)
        now = datetime.datetime.now()
        day_of_year = now.timetuple().tm_yday
        eyear = now.year
        if day_of_year <= 31:
            syear = eyear - 1
        else:
            syear = eyear

    elif quarterly:
        msg = "Processing LAADS data back to %d" % START_YEAR
        logger.info(msg)
        eyear = now.year
        syear = START_YEAR

    msg = 'Processing LAADS data for %d - %d' % (syear, eyear)
    logger.info(msg)
    for yr in range(eyear, syear-1, -1):
        msg = 'Processing year: %d' % yr
        logger.info(msg)
        status = getLadsData(auxdir, yr, today)
        if status == ERROR:
            msg = "Problems occurred while processing LAADS data for year " \
                "%d." % yr
            logger.error(msg)
            return ERROR

    msg = 'LAADS processing complete.'
    logger.info(msg)
    return SUCCESS

if __name__ == "__main__":
    # setup the default logger format and level. log to STDOUT.
    logging.basicConfig(format=('%(asctime)s.%(msecs)03d %(process)d'
                                ' %(levelname)-8s'
                                ' %(filename)s:%(lineno)d:'
                                '%(funcName)s -- %(message)s'),
                        datefmt='%Y-%m-%d %H:%M:%S',
                        level=logging.INFO)
    sys.exit (main())
