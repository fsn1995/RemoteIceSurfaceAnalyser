"""
Functions for classifying Sentinel 2 images using a trained classification model

"""

import numpy as np
import pandas as pd
import xarray as xr
import glob
import os
try:
    import joblib
except ImportError:
    from sklearn.externals import joblib

class SurfaceClassifier:

    # Bands to use in classifier
    s2_bands_use = ['B02', 'B03', 'B04', 'B05', 'B06', 'B07', 'B8A', 'B11', 'B12']

    # Level 2A scaling factor
    l2a_scaling_factor = 10000

    # names of bands as used in classifier
    NAME_bands = 'bands'
    NAME_x = 'x'
    NAME_y = 'y'

    def __init__(self, pkl):
        """ Initialise classifier. 

        :param pkl: path of pickled classifier.
        :type pkl: str

        """
        self.classifier = joblib.load(pkl)

        return



    def load_img_to_xr(self, img_path, resolution, Icemask, Cloudmask):
        """ Load Sentinel-2 JP2000s into xr.Dataset.

        Load all bands of image (specified by s2_bands_use) into an xarray
        Dataset, include Icemask and Cloudmask, return the in-memory Dataset.
        Applies scaling factor.

        """
        
        # Open link to each image
        store = []
        for band in self.s2_bands_use:
            fn = glob.glob('%s*%s_%sm.jp2' %(img_path,band,resolution))
            
            if len(fn) > 1:
                raise ValueError
            else:
                fn = fn[0]
            
            da_band = xr.open_rasterio(fn, chunks={self.NAME_x: 2000, self.NAME_y: 2000})
            crs = da_band.attrs['crs']
            # Apply scaling factor
            da_band = da_band / self.l2a_scaling_factor
            da_band[self.NAME_bands] = band
            store.append(da_band)
        
        # Concatenate all bands into a single DataArray
        da = xr.concat(store, dim=self.NAME_bands).squeeze()

        # Create complete dataset
        ds = xr.Dataset({ 'Data': ((self.NAME_bands,self.NAME_y,self.NAME_x), da),
                          'Icemask': ((self.NAME_y,self.NAME_x), Icemask),
                          'Cloudmask': ((self.NAME_y,self.NAME_x), Cloudmask) },
                          coords={self.NAME_bands:self.s2_bands_use, 
                                  self.NAME_y:da_band[self.NAME_y],
                                  self.NAME_x:da_band[self.NAME_x]})

        ds.Data.attrs['crs'] = crs

        return ds


    def classify_image(self, S2vals, savepath, tile, date, 
        savefigs=True):
        """ Apply classifier to image.

        function applies pickled classifier to multispectral S2 image saved as
        NetCDF, saving plot and summary data to output folder.
        """

        # stack the values into a 1D array
        stacked = S2vals.Data.stack(allpoints=[self.NAME_y,self.NAME_x])

        # Transpose and rename so that DataArray has exactly the same layout/labels as the training DataArray.
        # mask out nan areas not masked out by GIMP
        stackedT = stacked.T
        stackedT = stackedT.rename({'allpoints': 'samples'})

        # apply classifier
        predicted = self.classifier.predict(stackedT)

        # Unstack back to x,y grid
        predicted = predicted.unstack(dim='samples')

        return predicted


    def calculate_albedo(self, S2vals):
        """ Calculate albedo using Liang et al (2002) equation

        For some reason B8A is being used in unforked version of repo, even
        though Naegeli uses B08...

        See also Naegeli et al 2017, Remote Sensing
        """
        
        albedo = (  0.356 * S2vals.Data.loc[{self.NAME_bands:'B02'}] \
                  + 0.130 * S2vals.Data.loc[{self.NAME_bands:'B04'}] \
                  + 0.373 * S2vals.Data.loc[{self.NAME_bands:'B8A'}] \
                  + 0.085 * S2vals.Data.loc[{self.NAME_bands:'B11'}] \
                  + 0.072 * S2vals.Data.loc[{self.NAME_bands:'B12'}] \
                  - 0.0018 )

        return albedo

    
    def combine_masks(self, S2vals):
        """ Combine ice mask and cloud masks """

        mask2 = (S2vals.Icemask.values == 1)  \
              & (S2vals.Data.sum(dim=self.NAME_bands) > 0) \
              & (S2vals.Cloudmask.values == 0)

        return mask2


    def invert_snicar(self, S2vals, mask2):

        """
        Pixelwise retrieval of snicar RT params by matching spectra against snicar-generated LUT loaded from process_dir

        """

        print("\nRETRIEVING SNICAR PARAMS")
        band_idx = pd.Index([1, 2, 3, 4, 5, 6, 7, 8, 9], name='bands')

        # concatenate the bands into a single dimension ('bands_idx') in the data array
        concat = xr.concat([S2vals.Data.loc[{self.NAME_bands:'B02'}], S2vals.Data.loc[{self.NAME_bands:'B03'}], 
        S2vals.Data.loc[{self.NAME_bands:'B04'}], S2vals.Data.loc[{self.NAME_bands:'B05'}], S2vals.Data.loc[{self.NAME_bands:'B06'}], 
        S2vals.Data.loc[{self.NAME_bands:'B07'}],S2vals.Data.loc[{self.NAME_bands:'B8A'}], S2vals.Data.loc[{self.NAME_bands:'B11'}], S2vals.Data.loc[{self.NAME_bands:'B12'}]], band_idx)

        # stack the values into a 1D array
        stacked = concat.stack(allpoints=['y', 'x'])

        # Transpose and rename so that DataArray has exactly the same layout/labels as the training DataArray.
        # mask out nan areas not masked out by GIMP
        stackedT = stacked.T
        stackedT = stackedT.rename({'allpoints': 'samples'})

        # copy range of values used to generate LUT. THESE MUST MATCH THOSE USED TO BUILD LUT!!!
        side_lengths = [[3000,3000,3000,3000,3000],[5000,5000,5000,5000,5000],[7000,7000,7000,7000,7000],[9000,9000,9000,9000,9000],[12000,12000,12000,12000,12000],[15000,15000,15000,15000,15000]]
        densities = [[300,300,300,300,300],[400,400,400,400,400],[500,500,500,500,500],[600,600,600,600,600],[700,700,700,700,700],[800,800,800,800,800],[900,900,900,900,900]]
        dust = [[10000,0,0,0,0],[50000,0,0,0,0],[100000,0,0,0,0],[500000,0,0,0,0],[1000000,0,0,0,0],[1500000,0,0,0,0],[2000000,0,0,0,0]]
        algae = [[10000,0,0,0,0],[50000,0,0,0,0],[100000,0,0,0,0],[500000,0,0,0,0],[1000000,0,0,0,0],[1500000,0,0,0,0],[2000000,0,0,0,0]]
        wavelengths = np.arange(0.3,5,0.01)

        # set index in wavelength array corresponding to centre WL for each S2 band
        # e.g. for idx[0] == 19, wavelengths[19] = 490 nm
        idx = [19, 26, 36, 40, 44, 48, 56, 131, 190]

        # RECHUNK STACKEDT: choice of chunk size is crucial for maximising speed while preventing memory over-allocation.
        # While 10000 seems small there are very large intermediate arrays spawned by the compute() function.

        stackedT = stackedT.chunk(20000,9)

        # reformat LUT: flatten to 2D array with column per combination of RT params, row per wavelength
        dirtyLUT = np.load(str(os.environ['PROCESS_DIR'] + 'SNICAR_LUT_2058.npy')).reshape(len(side_lengths)*len(densities)*len(dust)*len(algae),len(wavelengths))
        array = []

        # find most similar SNICAR spectrum for each pixel
        # astype(float 16) to reduce memory allocation (default was float64)
        dirtyLUT = dirtyLUT[:,idx] # reduce wavelengths to match sample spectrum
        dirtyLUT = xr.DataArray(dirtyLUT,dims=('spectrum','bands')).astype(np.float16)
        error_array = dirtyLUT-stackedT.astype(np.float16) # subtract reflectance from snicar reflectance pixelwise

        # average error over bands, then provide index of minimum error (index refers to position in flattened LUT for closest matching spectrum)
        idx_array = xr.apply_ufunc(abs,error_array,dask='allowed').mean(dim='bands').argmin(dim='spectrum') 
        idx_array.compute() # compute delayed product from transformation in previous line

        # unravel index computes the index in the original n-dimeniona LUT from the index in the flattened LUT 
        param_array = np.array(np.unravel_index(idx_array,[len(side_lengths),len(densities),len(dust),len(algae)]))

        # flush disk
        idx_array = None
        error_array = None
        dirtyLUT = None

        #use the indexes to retrieve the actual parameter values for each pixel from the LUT indexes
        # since the values are equal for all layers (side_lengths and density) or only the top layer (LAPs)
        # only the first value from the parameeter arrays are taken.

        counter = 0
        param_names = ['side_lengths','densities','dust','algae']
        for param in [side_lengths, densities, dust, algae]:

            for i in np.arange(0,len(param),1):
                
                if i ==0:
                    result_array = np.where(param_array[counter]==i, param[i][0], param_array[counter])
                else:
                    result_array = np.where(param_array[counter]==i, param[i][0], result_array)

            result_array = result_array.reshape(int(np.sqrt(len(stackedT))),int(np.sqrt(len(stackedT))))
            
            resultxr = xr.DataArray(data=result_array,dims=['y','x'], coords={'x':S2vals.x, 'y':S2vals.y}).chunk(2000,2000)
            resultxr = resultxr.where(mask2>0)
            resultxr.to_netcdf(str(os.environ['PROCESS_DIR']+ f"{param_names[counter]}.nc"))

            counter +=1

        # retrieved params are saved as temporary netcdfs to the process_dir and then loaded into the final dataset in run_classifier.py

        return



    def albedo_report(self, tile, date, savepath):
        """ Report albedo in each surface type. 

        TODO: Refactor to cope with different surface type labels 

        """

        with xr.open_dataset(savepath + f"{tile}_{date}_Classification_and_Albedo_Data.nc",
                             chunks={'x': 2000, 'y': 2000}) as dataset:


            predicted = dataset.classified.to_series()
            albedo = dataset.albedo.to_series()

            albedoDF = pd.DataFrame({'predicted':predicted, 'albedo':albedo})
            
            countDF = albedoDF.groupby(['predicted']).count()
            summaryDF = albedoDF.groupby(['predicted']).describe()['albedo']
            summaryDF = summaryDF.squeeze()

            # Check for surface classes not found in image and add them into
            # the results summary.
            to_concat = {}
            for n in np.arange(1,7):
                try:
                    v = summaryDF.loc[n]
                except KeyError:
                    to_concat[n] = dict(max=0)

            newSummaryDF = pd.concat((summaryDF, pd.DataFrame.from_dict(to_concat, orient='index')),
                axis=0, sort=False)

            ####################################

            summaryxr = xr.DataArray(newSummaryDF, dims=('classID', 'metric'),
                                     coords={'classID': ['SN', 'WAT', 'CC', 'CI', 'LA', 'HA'],
                                             'metric': ['count', 'mean', 'std', 'min', '25%', '50%', '75%', 'max'],
                                             }, attrs={'date': date})

            summaryxr.to_netcdf(str(savepath+f'summary_data_{tile}_{date}.nc'))

            algal_coverage = (sum(summaryxr.sel(classID=['HA', 'LA'], metric='count')) / (
                sum(summaryxr.sel(classID=['HA','LA','WAT', 'CC', 'CI'], metric='count').values))) * 100

            #####################################

        return newSummaryDF



    def concat_all_dates(self, savepath, tile):

        """
        Function concatenates xarrays from individual dates into one master dataset for each tile.
        The dimensions are: date, classID and metric
        The coordinates on each dimension are accessed by their index in the following lists:
        date [0: 1st date, 1: 2nd date, 2: 3rd date]
        classID [0: SN, 1: WAT , 2: CC, 3: CI, 4: LA, 5: HA]
        metric [0: count, 1: mean, 2: std, 3: min, 4: 25% , 5: 50% , 6: 75%, 7: max ]
        The order of the indexes is: concat_data[date, ID, metric]
        so to access the total number of pixels classed as snow on the first date:
        >> concat_dataset[0,0,0].values
        to access the mean albedo of cryoconite covered pixels on all dates:
        >> concat_dataset[:,2,1].values
        or alternatively use xr.sel() which allows indexing by label, e.g.:
        concat_dataset.sel(classID = 'HA', metric = 'mean', date = '20160623')
        :param masterDF:
        :return:
        """

        data = []
        ds = []
        dates = []

        xrlist = glob.glob(str(savepath + 'summary_data_' + '*.nc')) # find all summary datasets

        for i in np.arange(0,len(xrlist),1):
            ds = xr.open_dataarray(xrlist[i])
            data.append(ds)
            date = ds.date
            dates.append(date)

            try:
                concat_data = xr.concat(data, dim=pd.Index(dates, name='date'))

                savefilename = str(savepath+f'summary_data_all_dates_{tile}.nc')
                concat_data.to_netcdf(savefilename,'w')
                concat_data = None  # flush

            except:
                print("could not concatenate output files - there is probably only one output file available")

        return


    def LAP_report(self, tile, date, savepath):
        """  

        Report summary stats for dus and algae 

        """

        with xr.open_dataset(savepath + f"{tile}_{date}_Classification_and_Albedo_Data.nc",
                             chunks={'x': 2000, 'y': 2000}) as dataset:

            algae = dataset.algae.to_series()
            dust = dataset.dust.to_series()

            LAP_DF = pd.DataFrame({'algae':algae, 'dust':dust})
            
            total_biomass = LAP_DF['algae'].sum()
            total_dust = LAP_DF['dust'].sum()

            max_biomass = LAP_DF['algae'].max()
            max_dust = LAP_DF['dust'].max()

            min_biomass = LAP_DF['algae'].min()
            min_dust = LAP_DF['dust'].min()

            LAP_DF = LAP_DF.squeeze()


            ####################################

            summaryxr = xr.DataArray(newSummaryDF, dims=('classID', 'metric'),
                                     coords={'classID': ['SN', 'WAT', 'CC', 'CI', 'LA', 'HA'],
                                             'metric': ['count', 'mean', 'std', 'min', '25%', '50%', '75%', 'max'],
                                             }, attrs={'date': date})

            summaryxr.to_netcdf(str(savepath+f'summary_data_{tile}_{date}.nc'))

            algal_coverage = (sum(summaryxr.sel(classID=['HA', 'LA'], metric='count')) / (
                sum(summaryxr.sel(classID=['HA','LA','WAT', 'CC', 'CI'], metric='count').values))) * 100

            #####################################

        return newSummaryDF