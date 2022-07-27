from dataclasses import dataclass
import re
from pathlib import Path
from typing import Union, NamedTuple, Any
import numpy as np
from numpy.typing import NDArray
from matplotlib import pyplot as plt
import pandas as pd


class CrasHeader(NamedTuple):
    id: str  # starts with "CoreLog Linescan ".   If it starts with "CoreLog Linescan 1." then it supports compression (otherwise ignore ctype).
    ns: int  # image width in pixels
    nl: int  # image height in lines
    nb: int  # number of bands (1 or 3  but always 3 for HyLogger 1 / 2 / 3)
    org: int  # interleave (1=BIL  2=BIP  and compressed rasters are always BIP while uncompressed ones are always BIL)
    dtype: int  # datatype (unused  always byte)
    specny: int  # number of linescan lines per dataset sample
    specnx: int  # unused
    specpx: int  # unused  intended to be the linescan column that relates to the across-scan position of the (1D) spectral dataset
    ctype: int  # compression type (0=uncompressed  1=jpeg chunks)
    chunksize: int  # number of image lines per chunk for jpeg-compressed rasters
    nchunks: int  # number of compressed image chunks (jpeg compression)
    csize32_obs: int  # size in bytes of comressed image data (OBSOLETE - not used anywhere any more.   However it will be set in old linescan rasters so I cant easily recycle it.   Also  there are some compressed rasters out there that are >4GB in size)
    ntrays: int  # number of trays (number of tray-table records after the image data)
    nsections: int  # number of sections (number of section-table records after the image data)
    finerep: int  # chip-mode datasets - number of spectral measurements per chip bucket (and theres one image frame per bucket)
    jpqual: int  # jpeg quality factor  0..100 (jpeg compression)


class TrayInfo(NamedTuple):
    utlengthmm: float  # "untrimmed" length of tray imagery in mm
    baseheightmm: float  # height of bottom of tray above table
    coreheightmm: float  # height of (top of) core above ..something or other (I don't actually use it for the linescan raster)
    nsections: int  # number of core sections
    nlines: int  # number of image lines in this tray


class SectionInfo(NamedTuple):
    utlengthmm: float  # untrimmed length of imagery in mm (could be less than the tray's)
    startmm: float  # start position (along scan) in mm
    endmm: float  # end position in mm
    trimwidthmm: float  # active (section-overlap-corrected) image width in mm
    startcol: int  # number of image lines in this tray
    endcol: int  # end pixel across for active (section-overlap-corrected) imagery
    nlines: int  # number of image lines in this section


@dataclass
class Spectra:
    spectrum_name: str
    spectra: NDArray
    wavelength: NDArray
    bandheaders: "list[str]"
    sampleheaders: pd.DataFrame

@dataclass
class TSG:
    nir: Spectra
    tir: Spectra


def read_tsg_file(filename: Union[str, Path]) -> "list[str]":
    """Reads the files with the .tsg extension which are almost a toml file
    but not quite so the standard parser doesn't work

    Quite simply this function reads the file and strips the newlines at the end
    to simplify processing later on

    """
    lines: list[str] = []
    tmp_line: str
    with open(filename) as file:
        for line in file:
            tmp_line = line.rstrip()
            lines.append(tmp_line)
    return lines


def find_header_sections(tsg_str: "list[str]"):
    """Finds the header sections of the .tsg file
    header sections are defined as strings between square brackets
    """
    re_strip: re.Pattern = re.compile("^\\[[a-zA-Z0-9 ]+\\]")
    positions: "list[int]" = []
    for i, s in enumerate(tsg_str):
        if len(re_strip.findall(s)) > 0:
            positions.append(i)
    positions.append(len(tsg_str))
    n_headers: int = len(positions)
    sections: "dict[str, tuple[int,int]]" = {}
    tmp_section: "tuple[int,int]"
    tmp_name: str
    for i in range(n_headers - 1):
        tmp_section = (positions[i] + 1, positions[i + 1] - 1)
        tmp_name = tsg_str[positions[i]].strip("[]")
        sections.update({tmp_name: tmp_section})
    return sections


def extract_section(fstr: str, header_sections: "dict[str, tuple[int]]") -> "list[int]":
    return [1]


def parse_section(
    section_list: "list[str]", key_split: str = ":"
) -> "list[dict[str, str]]":
    final: list[dict[str, str]] = []
    key_0: str
    tmp_sample: dict[str, str]

    for i in section_list:
        kk = parse_kvp(i, ":")
        k0 = list(kk.keys())
        key_0: str = k0[0]
        tmp_sample = {}
        tmp_sample.update({"sample": key_0})
        for j in kk[key_0].split():
            tmp_keys = parse_kvp(j)
            if not tmp_keys is None:
                tmp_sample.update(tmp_keys)
        final.append(tmp_sample)

    return final


def parse_tsg(
    fstr: list[str], headers: "dict[str, tuple[int,int]]"
) -> "dict[str, Any]":
    d_info: dict[str, Any] = {}
    sample_header: list[dict[str, str]] = []
    start: int
    end: int

    for k in headers.keys():
        start = headers[k][0]
        end = headers[k][1]
        if k == "sample headers":
            sample_header = parse_section(fstr[start:end], ":")
            d_info.update({k: pd.DataFrame(sample_header)})
        elif k == "wavelength specs":
            split_wavelength = fstr[start:end][0].split()
            tmp_wave = {
                "start": float(split_wavelength[0]),
                "end": float(split_wavelength[1]),
                "unit": split_wavelength[-1],
            }

            d_info.update({k: tmp_wave})
        elif k == "band headers":
            sample_header = parse_section(fstr[start:end], ":")
            d_info.update({k: pd.DataFrame(sample_header)})
        else:
            tmp_out: dict[str, str] = {}
            for i in fstr[start:end]:
                tmp = parse_kvp(i)
                if not tmp is None:
                    tmp_out.update(tmp)
            d_info.update({k: tmp_out})

    return d_info


def parse_kvp(line: str, split: str = "=") -> "dict[str, str]":
    """parses strings into Key value pairs
    control over the split value is to manage the different seperators used
    in different sections of the file

    Args:
        line: the current line to parse
    Returns:
        a dictionary with key and value
    Examples:
        >>> line = 'name=ben'
        >>> parse_kvp(line)
        >>> {'name':'ben'}
    """
    if line.find(split) >= 0:
        split_line = line.split(split)
        key = split_line[0].strip()
        value = split_line[1].strip()
        kvp = {key: value}
    else:
        kvp = {}
    return kvp


def read_bip(filename: Union[str, Path], coordinates: "dict[str, str]") -> NDArray:
    """reads the .bip file as a 1d array then reshapes it according to the dimensions
    as supplied in the coordinates dict

    Args:
        filename: location of the .bip file
        coordinates: dimension of the .bip file
    Returns:
        a 3d numpy array the first dimension corresponds to the spectra and mask
        the second the samples
        the third the bands
    Examples:
    """
    # load array in 1d
    tmp_array: NDArray[np.float32] = np.fromfile(filename, dtype=np.float32)

    # extract information on array shape
    n_bands: int = int(coordinates["lastband"])
    n_samples: int = int(coordinates["lastsample"])
    # reshape array
    spectrum = np.reshape(tmp_array, (2, n_samples, n_bands))
    return spectrum


def calculate_wavelengths(
    wavelength_specs: "dict[str,float]", coordinates: "dict[str, str]"
) -> NDArray:
    wavelength_range: float = wavelength_specs["end"] - wavelength_specs["start"]
    resolution: float = wavelength_range / (int(coordinates["lastband"]) - 1)

    return np.arange(
        wavelength_specs["start"], wavelength_specs["end"] + resolution, resolution
    )


def read_hires_dat(filename: Union[str, Path]) -> NDArray:
    """read the *hires.dat file which contains the lidar scan
    of the material

    Args:
        filename: location of the .dat file
    Returns:
        np.ndarray representing the
    Examples:
    """
    # the hires .dat file is f32 and the actual data starts at pos 640
    # the rest is probably information pertaining to the instrument itself
    lidar = np.fromfile(filename, dtype=np.float32, offset=640)
    return lidar


def parse_sample_headers(section: list[str]) -> pd.DataFrame:
    """Parses the sample headers section of the .tsg file"""
    tmp_sample: dict[str, str]
    final_sample: list[dict[str, str]] = []
    key_0: str
    i: str
    sample_header: pd.DataFrame
    for i in section:
        kk = parse_kvp(i, ":")
        k0 = list(kk.keys())
        key_0: str = k0[0]
        tmp_sample = {}
        tmp_sample.update({"sample": key_0})
        for j in kk[key_0].split():
            tmp_keys = parse_kvp(j)
            if not tmp_keys is None:
                tmp_sample.update(tmp_keys)
        final_sample.append(tmp_sample)
    sample_header = pd.DataFrame(final_sample)
    return sample_header


def parse_wavelength_specs(line: str) -> "dict[str, Union[float,str]]":

    split_wavelength: list[str] = line.split()
    wavelength = {
        "start": float(split_wavelength[0]),
        "end": float(split_wavelength[1]),
        "unit": split_wavelength[-1],
    }
    return wavelength


def parse_tsg_bip_pair(tsg_file: Path, bip_file: Path, spectrum: str) -> Spectra:
    fstr = read_tsg_file(tsg_file)
    headers = find_header_sections(fstr)
    info = parse_tsg(fstr, headers)
    spectra = read_bip(bip_file, info["coordinates"])
    wavelength = calculate_wavelengths(info["wavelength specs"], info["coordinates"])
    package = Spectra(spectrum, spectra, wavelength,info['band headers'],info['sample headers'])

    return package


class FilePairs:
    """Class for keeping track of an item in inventory."""

    nir_tsg: Path
    nir_bip: Path
    tir_tsg: Path
    tir_bip: Path
    lidar: Path
    cras: Path

    def _get_nir(self) -> "Union[tuple[Path,Path], None]":
        has_tsg: bool = isinstance(self.nir_tsg, Path)
        has_bip: bool = isinstance(self.nir_bip, Path)
        names_match: bool = self.nir_bip.stem == self.nir_tsg.stem
        if has_bip and has_tsg and names_match:
            pairs = (self.nir_tsg, self.nir_bip)
        else:
            pairs = None
        return pairs

    def _get_tir(self) -> "Union[tuple[Path,Path], None]":
        has_tsg: bool = isinstance(self.nir_tsg, Path)
        has_bip: bool = isinstance(self.nir_bip, Path)
        names_match: bool = self.nir_bip.stem == self.nir_tsg.stem
        if has_bip and has_tsg and names_match:
            pairs = (self.nir_tsg, self.nir_bip)
        else:
            pairs = None
        return pairs

    def _get_lidar(self) -> Union[Path, None]:
        has_lidar: bool = isinstance(self.lidar, Path)
        if has_lidar:
            pairs = self.lidar
        else:
            pairs = None
        return pairs

    def _get_cras(self) -> Union[Path, None]:
        has_cras: bool = isinstance(self.cras, Path)
        if has_cras:
            pairs = self.cras
        else:
            pairs = None
        return pairs

    def valid_nir(self) -> bool:
        result = self._get_nir()
        if result is None:
            valid = False
        else:
            valid = True
        return valid

    def valid_tir(self) -> bool:
        result = self._get_tir()
        if result is None:
            valid = False
        else:
            valid = True
        return valid

    def valid_lidar(self) -> bool:
        result = self._get_lidar()
        if result is None:
            valid = False
        else:
            valid = True
        return valid

    def valid_cras(self) -> bool:
        result = self._get_cras()
        if result is None:
            valid = False
        else:
            valid = True
        return valid


foldername = "/home/ben/pyrexia/data/ETG0187"


def parse_package(foldername: Union[str, Path]):
    # convert string to Path because we are wanting to use Pathlib objects to manage the folder structure
    if isinstance(foldername, str):
        foldername = Path(foldername)
    # we are parsing the folder structure here and checking that
    # pairs of files exist in this case we are making sure
    # that there are .tsg files with corresponding .bip files
    # we will parse the lidar height data because we can

    # process here is to map the files that we need together
    # tir and nir files
    #
    # deal the files to the type

    files = foldername.glob("*.*")
    f: Path
    file_pairs = FilePairs()
    for f in files:
        if f.name.endswith("tsg.tsg"):
            setattr(file_pairs, "nir_tsg", f)

        elif f.name.endswith("tsg.bip"):
            setattr(file_pairs, "nir_bip", f)

        elif f.name.endswith("tsg_tir.tsg"):
            setattr(file_pairs, "tir_tsg", f)

        elif f.name.endswith("tsg_tir.bip"):
            setattr(file_pairs, "tir_bip", f)

        elif f.name.endswith("tsg_cras.bip"):
            setattr(file_pairs, "cras", f)

        elif f.name.endswith("tsg_hires.dat"):
            setattr(file_pairs, "lidar", f)
        else:
            pass

    # once we have paired the .tsg and .bip files run the reader
    # for the nir/swir and then tir
    # read nir/swir
    if file_pairs.valid_nir():
        nir = parse_tsg_bip_pair(file_pairs.nir_tsg, file_pairs.nir_bip,'nir')
        
    if file_pairs.valid_tir():
        tir = parse_tsg_bip_pair(file_pairs.tir_tsg, file_pairs.tir_bip,'tir')
    
    
