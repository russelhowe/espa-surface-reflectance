/*****************************************************************************
FILE: comptemp.c
  
PURPOSE: Contains the function for calculating the temperature at the scene
center.

PROJECT:  Land Satellites Data System Science Research and Development (LSRD)
at the USGS EROS

LICENSE TYPE:  NASA Open Source Agreement Version 1.3

NOTES:
*****************************************************************************/

#include <stdio.h> 
#include <stdlib.h> 
#include "error_handler.h"

/*****************************************************************************
MODULE: comptemp
  
PURPOSE: Reads in the scene center time and the file containing the four
air temp values for the acquisition date (temp values are available at 0 hr,
6 hr, 12 hr, and 18 hr).

RETURN VALUE:
Type = int
Value           Description
-----           -----------
ERROR           Error computing scene center temp
SUCCESS         Successfully computed the scene center temp

NOTES:
*****************************************************************************/
int main(int argc, char **argv)
{
    char errmsg[STR_SIZE];           /* error message */
    char FUNC_NAME[] = "comptemp";   /* function name */
    int i;            /* looping variable */
    float temp[5];    /* four input temps plus one 24 hours after first (K) */
    float time[5];    /* four input times plus one 24 hours after first */
    float sc_temp;    /* scene center temp (Kelvin) */
    float sc_time;    /* scene center time (in decimal hours) */
    float slp;        /* slope of the temps */
    FILE *fp=NULL;    /* file pointer for airtemp file */
    FILE *scene_center_fp=NULL; /* file pointer for scene center temp file */

    /* Check the arguments */
    if (argc < 3 || argc > 5)
    {
        sprintf (errmsg, "usage: %s <scene center time (decimal hours (24 hr)> "
            "<input airtemp file (0 hr, 6 hr, 12 hr, 18 hr)> "
            "[<optional scene center temperature output file>]\n", argv[0]);
        error_handler (true, FUNC_NAME, errmsg);
        exit (ERROR);
    }

    /* Grab the scene center time */
    sc_time = atof (argv[1]);

    /* Open the air temp file for reading */
    fp = fopen (argv[2], "r");
    if (fp == NULL)
    {
        sprintf (errmsg, "Error opening air temp file: %s", argv[2]);
        error_handler (true, FUNC_NAME, errmsg);
        exit (ERROR);
    }

    /* Open the scene center temperature file for writing if requested to */
    if (argc == 4)
    {
        scene_center_fp = fopen (argv[3], "w");
        if (scene_center_fp == NULL)
        {
            sprintf (errmsg, "Error opening : %s", argv[3]);
            error_handler (true, FUNC_NAME, errmsg);
            exit (ERROR);
        }
    }

    /* Read the 4 temperature values from the airtemp file */
    for (i = 0; i < 4; i++)
    {
        fscanf (fp, "%f", &temp[i]);
        time[i] = i * 6.0;
    }
    temp[4] = temp[0];
    time[4] = 24.0;

    /* Validate the scene center time */
    if (sc_time < 0.01)
        sc_time = 0.01;
         
    /* Find the correct location in the group of time values where the
       scene center time is larger than the time for the air temp */
    i = 0;
    while (sc_time > time[i])
        i++;

    /* Determine the temperature at the scene center based on the current
       and previous temps */
    slp = (temp[i]-temp[i-1]) / 6.0;
    sc_temp = temp[i-1] + slp * (sc_time - time[i-1]);

    printf ("%f\n", sc_temp);

    /* If requested, write the result to a file. */
    if (argc == 4)
    {
        fprintf (scene_center_fp, "%f\n", sc_temp);
        fclose (scene_center_fp);
    }

    exit (SUCCESS);
}
