import java.io.*;
import java.nio.file.*;
import java.nio.charset.StandardCharsets;
import io.mosip.esignet.core.dto.vci.VCIssuanceTransaction;

/** Offline compatibility oracle only; never loaded by the native service. */
public class CredentialNonceOracle {
    public static void main(String[] args) throws Exception {
        VCIssuanceTransaction transaction;
        try (ObjectInputStream input = new ObjectInputStream(Files.newInputStream(Path.of(args[0])))) {
            transaction = (VCIssuanceTransaction) input.readObject();
        }
        String expected = Files.readString(Path.of(args[1]), StandardCharsets.UTF_8);
        if (!expected.equals(transaction.getCNonce()) || transaction.getCNonceIssuedEpoch() <= 0 ||
            transaction.getCNonceExpireSeconds() <= 0) throw new IllegalStateException("Native nonce state mismatch");
        transaction.setCNonce("original-oracle-rotated-nonce");
        try (ObjectOutputStream output = new ObjectOutputStream(Files.newOutputStream(Path.of(args[2])))) {
            output.writeObject(transaction);
        }
        System.out.println("ORIGINAL_NONCE_STATE_READ_AND_ROTATED=true");
    }
}
